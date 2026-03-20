# coding=utf-8
"""Tests for torrent file ignore regex feature in medusa/search/core.py."""
from __future__ import unicode_literals

import logging

from bencodepy import DEFAULT as BENCODE

from medusa.search.core import (
    _check_torrent_file_ignore_regex,
    _get_torrent_file_list,
    _try_get_torrent_content_for_magnet,
)

from mock.mock import Mock, patch

import pytest


def _make_single_file_torrent(name):
    """Create bencode-encoded torrent content with a single file.

    :param name: filename (bytes or str)
    :return: bencoded bytes
    """
    if isinstance(name, str):
        name = name.encode('utf-8')
    return BENCODE.encode({
        b'info': {
            b'name': name,
            b'piece length': 262144,
            b'pieces': b'x' * 20,
            b'length': 1024,
        }
    })


def _make_multi_file_torrent(file_paths):
    """Create bencode-encoded torrent content with multiple files.

    :param file_paths: list of file path lists, e.g. [[b'video.mkv'], [b'sub', b'english.srt']]
    :return: bencoded bytes
    """
    files = []
    for path_parts in file_paths:
        encoded_parts = []
        for part in path_parts:
            if isinstance(part, str):
                part = part.encode('utf-8')
            encoded_parts.append(part)
        files.append({b'length': 1024, b'path': encoded_parts})

    return BENCODE.encode({
        b'info': {
            b'name': b'TorrentName',
            b'piece length': 262144,
            b'pieces': b'x' * 20,
            b'files': files,
        }
    })


# ---- Tests for _get_torrent_file_list ----

class TestGetTorrentFileList(object):
    """Tests for _get_torrent_file_list."""

    def test_single_file_torrent(self):
        """Single-file torrent should return a list with the file name."""
        content = _make_single_file_torrent(b'Show.S01E01.720p.mkv')
        files = _get_torrent_file_list(content)
        assert files == ['Show.S01E01.720p.mkv']

    def test_multi_file_torrent(self):
        """Multi-file torrent should return all file paths."""
        content = _make_multi_file_torrent([
            [b'Show.S01E01.720p.mkv'],
            [b'Show.S01E01.nfo'],
            [b'Subs', b'English.srt'],
        ])
        files = _get_torrent_file_list(content)
        assert len(files) == 3
        assert 'Show.S01E01.720p.mkv' in files
        assert 'Show.S01E01.nfo' in files
        # Nested path joined with os.path.join
        assert any('English.srt' in f for f in files)

    def test_multi_file_with_exe(self):
        """Multi-file torrent with an exe should include it in the list."""
        content = _make_multi_file_torrent([
            [b'Show.S01E01.720p.mkv'],
            [b'setup.exe'],
        ])
        files = _get_torrent_file_list(content)
        assert 'setup.exe' in files

    def test_empty_content(self):
        """Empty content should return an empty list."""
        assert _get_torrent_file_list(b'') == []

    def test_none_content(self):
        """None content should return an empty list."""
        assert _get_torrent_file_list(None) == []

    def test_invalid_bencode(self):
        """Invalid bencode data should return an empty list."""
        assert _get_torrent_file_list(b'this is not valid bencode') == []

    def test_no_info_key(self):
        """Torrent without info key should return an empty list."""
        content = BENCODE.encode({b'comment': b'no info here'})
        assert _get_torrent_file_list(content) == []

    def test_empty_files_list_falls_back_to_name(self):
        """Torrent with empty files list should fall back to name field."""
        content = BENCODE.encode({
            b'info': {
                b'name': b'FallbackName',
                b'piece length': 262144,
                b'pieces': b'x' * 20,
                b'files': [],
            }
        })
        # Empty files list is falsy, so it falls back to the name field
        assert _get_torrent_file_list(content) == ['FallbackName']

    def test_no_name_no_files(self):
        """Torrent with no name and no files should return an empty list."""
        content = BENCODE.encode({
            b'info': {
                b'piece length': 262144,
                b'pieces': b'x' * 20,
            }
        })
        assert _get_torrent_file_list(content) == []


# ---- Tests for _check_torrent_file_ignore_regex ----

@pytest.mark.parametrize('p', [
    {  # p0: No regexes configured - should not ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [],
        },
        'files': [[b'Show.S01E01.mkv'], [b'setup.exe']],
        'expected': False,
    },
    {  # p1: exe regex matches a file - should ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'setup.exe']],
        'expected': True,
    },
    {  # p2: exe regex does not match any file - should not ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'Show.S01E01.nfo']],
        'expected': False,
    },
    {  # p3: Multiple regexes, second one matches - should ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.bat$', r'\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'malware.exe']],
        'expected': True,
    },
    {  # p4: Regex with negative lookahead - allows specific exe, blocks others
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'^(?!RARBG-DONOT-MIRROR\.exe$).+\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'RARBG-DONOT-MIRROR.exe']],
        'expected': False,
    },
    {  # p5: Regex with negative lookahead - blocks non-matching exe
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'^(?!RARBG-DONOT-MIRROR\.exe$).+\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'unknown_tool.exe']],
        'expected': True,
    },
    {  # p6: None content - should not ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.exe$'],
        },
        'content': None,
        'expected': False,
    },
    {  # p7: Single-file torrent matching regex - should ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.exe$'],
        },
        'single_file': b'malware.exe',
        'expected': True,
    },
    {  # p8: Case-insensitive matching not enabled by default
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.EXE$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'setup.exe']],
        'expected': False,
    },
    {  # p9: Case-insensitive regex with (?i) flag - should ignore
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'(?i)\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'setup.EXE']],
        'expected': True,
    },
    {  # p10: Nested path matching
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'\.exe$'],
        },
        'files': [[b'subfolder', b'installer.exe']],
        'expected': True,
    },
    {  # p11: Invalid regex pattern - should log warning and not crash
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'[invalid'],
        },
        'files': [[b'Show.S01E01.mkv']],
        'expected': False,
    },
    {  # p12: Mix of valid and invalid patterns - valid one matches
        'config': {
            'TORRENT_FILE_IGNORE_REGEX': [r'[invalid', r'\.exe$'],
        },
        'files': [[b'Show.S01E01.mkv'], [b'setup.exe']],
        'expected': True,
    },
])
def test_check_torrent_file_ignore_regex(p, app_config, caplog):
    """Test _check_torrent_file_ignore_regex with various patterns and file lists."""
    caplog.set_level(logging.DEBUG, logger='medusa')

    # Given
    config_attrs = p.get('config', {})
    for attr, value in config_attrs.items():
        app_config(attr, value)

    # Build torrent content
    if 'content' in p:
        content = p['content']
    elif 'single_file' in p:
        content = _make_single_file_torrent(p['single_file'])
    else:
        content = _make_multi_file_torrent(p.get('files', []))

    # When
    actual = _check_torrent_file_ignore_regex(content, 'Test.Torrent.Name')

    # Then
    assert actual == p['expected']


# ---- Tests for _try_get_torrent_content_for_magnet ----

class TestTryGetTorrentContentForMagnet(object):
    """Tests for _try_get_torrent_content_for_magnet."""

    MAGNET_URL = 'magnet:?xt=urn:btih:AB123456789012345678901234567890ABCDEF01&dn=Test.Show.S01E01'

    def _make_mock_result(self, url=None, bt_cache_urls=None, content_response=None):
        """Create a mock search result with a provider."""
        from medusa.providers.torrent.torrent_provider import TorrentProvider

        result = Mock()
        result.url = url or self.MAGNET_URL
        result.name = 'Test.Show.S01E01'

        provider = Mock(spec=TorrentProvider)
        provider.bt_cache_urls = bt_cache_urls or [
            'https://cache1.example.com/{info_hash}.torrent',
            'https://cache2.example.com/{info_hash}.torrent',
        ]
        provider._get_info_from_magnet = TorrentProvider._get_info_from_magnet

        mock_session = Mock()
        mock_session.get_content = Mock(return_value=content_response)
        provider.session = mock_session

        result.provider = provider
        return result

    def test_successful_resolution(self):
        """Magnet resolved via first cache URL returns valid torrent content."""
        torrent_content = _make_multi_file_torrent([
            [b'Show.S01E01.mkv'],
            [b'setup.exe'],
        ])
        result = self._make_mock_result(content_response=torrent_content)

        content = _try_get_torrent_content_for_magnet(result)

        assert content is not None
        files = _get_torrent_file_list(content)
        assert 'setup.exe' in files

    def test_no_bt_cache_urls(self):
        """No bt_cache_urls returns None."""
        result = self._make_mock_result(bt_cache_urls=[])

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_invalid_torrent_content_from_cache(self):
        """Invalid content from cache is rejected."""
        result = self._make_mock_result(content_response=b'<html>not a torrent</html>')

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_none_content_from_cache(self):
        """None response from cache returns None."""
        result = self._make_mock_result(content_response=None)

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_cache_url_format_with_info_hash(self):
        """Cache URL is formatted with the correct info hash."""
        torrent_content = _make_single_file_torrent(b'Show.S01E01.mkv')
        result = self._make_mock_result(content_response=torrent_content)

        _try_get_torrent_content_for_magnet(result)

        # Verify session.get_content was called with a formatted URL containing the hash
        call_args = result.provider.session.get_content.call_args
        called_url = call_args[0][0]
        assert 'AB123456789012345678901234567890ABCDEF01' in called_url

    def test_no_info_hash_in_magnet(self):
        """Magnet without info hash returns None."""
        result = self._make_mock_result(url='magnet:?dn=NoHash')

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_provider_without_bt_cache_urls_attr(self):
        """Provider without bt_cache_urls attribute returns None."""
        result = Mock()
        result.url = self.MAGNET_URL
        result.name = 'Test'
        result.provider = Mock(spec=[])  # Empty spec = no attributes

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_first_cache_fails_second_succeeds(self):
        """If first cache returns invalid data, second cache is tried."""
        torrent_content = _make_single_file_torrent(b'Show.S01E01.mkv')

        result = self._make_mock_result()
        # First call returns invalid data, second returns valid
        result.provider.session.get_content = Mock(
            side_effect=[b'invalid data', torrent_content]
        )

        content = _try_get_torrent_content_for_magnet(result)

        assert content is not None
        assert _get_torrent_file_list(content) == ['Show.S01E01.mkv']
        assert result.provider.session.get_content.call_count == 2

    def test_all_caches_fail(self):
        """If all caches fail, returns None."""
        result = self._make_mock_result()
        result.provider.session.get_content = Mock(side_effect=Exception('Connection error'))

        content = _try_get_torrent_content_for_magnet(result)

        assert content is None

    def test_integration_magnet_with_ignore_regex(self, app_config, caplog):
        """End-to-end: magnet resolved via cache is checked against ignore regex."""
        caplog.set_level(logging.DEBUG, logger='medusa')

        app_config('TORRENT_FILE_IGNORE_REGEX', [r'\.exe$'])

        torrent_content = _make_multi_file_torrent([
            [b'Show.S01E01.mkv'],
            [b'sneaky.exe'],
        ])
        result = self._make_mock_result(content_response=torrent_content)

        content = _try_get_torrent_content_for_magnet(result)
        assert content is not None

        should_ignore = _check_torrent_file_ignore_regex(content, result.name)
        assert should_ignore is True

    def test_integration_magnet_clean_torrent(self, app_config, caplog):
        """End-to-end: magnet resolved via cache passes when no files match."""
        caplog.set_level(logging.DEBUG, logger='medusa')

        app_config('TORRENT_FILE_IGNORE_REGEX', [r'\.exe$'])

        torrent_content = _make_multi_file_torrent([
            [b'Show.S01E01.mkv'],
            [b'Show.S01E01.nfo'],
        ])
        result = self._make_mock_result(content_response=torrent_content)

        content = _try_get_torrent_content_for_magnet(result)
        assert content is not None

        should_ignore = _check_torrent_file_ignore_regex(content, result.name)
        assert should_ignore is False
