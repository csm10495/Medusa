# coding=utf-8
"""Tests for torrent file filtering based on regex patterns."""
from __future__ import unicode_literals

import os
import tempfile

from bencodepy import DEFAULT as BENCODE

from medusa import app
from medusa.providers.torrent.torrent_provider import TorrentProvider

import pytest

from mock import Mock, patch


class TestTorrentFileFiltering(object):
    """Test torrent file filtering with regex patterns."""

    @pytest.fixture
    def provider(self):
        """Create a mock torrent provider."""
        provider = TorrentProvider('TestProvider')
        provider.session = Mock()
        return provider

    def create_torrent_file(self, file_names, single_file=False):
        """
        Create a valid .torrent file with specified file names.

        :param file_names: List of file names to include in the torrent
        :param single_file: If True, create a single-file torrent
        :return: Path to the created torrent file
        """
        if single_file:
            # Single file torrent
            meta_info = {
                b'info': {
                    b'name': file_names[0].encode('utf-8'),
                    b'piece length': 262144,
                    b'pieces': b'dummy_pieces_hash',
                    b'length': 1024
                }
            }
        else:
            # Multi-file torrent
            files = []
            for file_name in file_names:
                # Split path into components
                parts = file_name.split('/')
                files.append({
                    b'path': [p.encode('utf-8') for p in parts],
                    b'length': 1024
                })

            meta_info = {
                b'info': {
                    b'name': b'TorrentName',
                    b'piece length': 262144,
                    b'pieces': b'dummy_pieces_hash',
                    b'files': files
                }
            }

        # Create temporary file
        fd, path = tempfile.mkstemp(suffix='.torrent')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(BENCODE.encode(meta_info))
        except Exception:
            os.close(fd)
            raise

        return path

    @pytest.mark.parametrize('p', [
        {  # p0: No regex patterns configured - should pass
            'file_names': ['video.mkv', 'setup.exe'],
            'regex_patterns': [],
            'expected': True
        },
        {  # p1: Single file torrent with .exe - should be blocked
            'file_names': ['setup.exe'],
            'regex_patterns': [r'\.exe$'],
            'expected': False,
            'single_file': True
        },
        {  # p2: Multi-file torrent with .exe - should be blocked
            'file_names': ['video.mkv', 'crack/setup.exe', 'readme.txt'],
            'regex_patterns': [r'\.exe$'],
            'expected': False
        },
        {  # p3: Multi-file torrent without .exe - should pass
            'file_names': ['video.mkv', 'subtitles/english.srt', 'readme.txt'],
            'regex_patterns': [r'\.exe$'],
            'expected': True
        },
        {  # p4: Negative lookahead - block all .exe except specific one
            'file_names': ['video.mkv', 'RARBG-DONOT-MIRROR.exe'],
            'regex_patterns': [r'^(?!RARBG-DONOT-MIRROR\.exe$).+\.exe$'],
            'expected': True
        },
        {  # p5: Negative lookahead - block other .exe files
            'file_names': ['video.mkv', 'crack.exe', 'RARBG-DONOT-MIRROR.exe'],
            'regex_patterns': [r'^(?!RARBG-DONOT-MIRROR\.exe$).+\.exe$'],
            'expected': False
        },
        {  # p6: Multiple regex patterns - match first
            'file_names': ['video.mkv', 'malware.bat'],
            'regex_patterns': [r'\.exe$', r'\.bat$'],
            'expected': False
        },
        {  # p7: Multiple regex patterns - match second
            'file_names': ['video.mkv', 'script.cmd'],
            'regex_patterns': [r'\.exe$', r'\.cmd$'],
            'expected': False
        },
        {  # p8: Multiple patterns - no match
            'file_names': ['video.mkv', 'subtitles.srt'],
            'regex_patterns': [r'\.exe$', r'\.bat$', r'\.cmd$'],
            'expected': True
        },
        {  # p9: Complex regex pattern with path
            'file_names': ['video.mkv', 'crack/keygen.exe', 'readme.txt'],
            'regex_patterns': [r'crack/.*\.exe$'],
            'expected': False
        },
        {  # p10: Invalid regex pattern - should not crash
            'file_names': ['video.mkv', 'file.exe'],
            'regex_patterns': [r'[invalid(regex'],
            'expected': True  # Invalid regex is ignored, torrent passes
        },
        {  # p11: Empty string in patterns - should be skipped
            'file_names': ['video.mkv'],
            'regex_patterns': ['', r'\.exe$'],
            'expected': True
        },
        {  # p12: Case sensitive matching
            'file_names': ['video.mkv', 'Setup.EXE'],
            'regex_patterns': [r'\.exe$'],
            'expected': True  # Pattern is case sensitive, doesn't match .EXE
        },
        {  # p13: Case insensitive matching with (?i) flag
            'file_names': ['video.mkv', 'Setup.EXE'],
            'regex_patterns': [r'(?i)\.exe$'],
            'expected': False  # Should match case insensitively
        },
    ])
    def test_verify_download_with_regex_filtering(self, provider, p, app_config):
        """Test _verify_download with various regex patterns."""
        # Given
        file_names = p['file_names']
        regex_patterns = p['regex_patterns']
        expected = p['expected']
        single_file = p.get('single_file', False)

        # Configure app with regex patterns
        app.IGNORE_TORRENTS_WITH_FILE_REGEX = regex_patterns

        # Create a temporary torrent file
        torrent_path = self.create_torrent_file(file_names, single_file=single_file)

        try:
            # When
            result = provider._verify_download(torrent_path)

            # Then
            assert result == expected, \
                f"Expected {expected}, got {result} for patterns {regex_patterns} and files {file_names}"

        finally:
            # Cleanup
            if os.path.exists(torrent_path):
                os.remove(torrent_path)

    def test_get_torrent_files_list_single_file(self, provider):
        """Test _get_torrent_files_list with single-file torrent."""
        # Given
        meta_info = {
            b'info': {
                b'name': b'video.mkv',
                b'length': 1024
            }
        }

        # When
        files = provider._get_torrent_files_list(meta_info)

        # Then
        assert files == ['video.mkv']

    def test_get_torrent_files_list_multi_file(self, provider):
        """Test _get_torrent_files_list with multi-file torrent."""
        # Given
        meta_info = {
            b'info': {
                b'name': b'TorrentName',
                b'files': [
                    {b'path': [b'video.mkv'], b'length': 1024},
                    {b'path': [b'subs', b'english.srt'], b'length': 512},
                    {b'path': [b'crack', b'keygen.exe'], b'length': 256}
                ]
            }
        }

        # When
        files = provider._get_torrent_files_list(meta_info)

        # Then
        assert files == ['video.mkv', 'subs/english.srt', 'crack/keygen.exe']

    def test_get_torrent_files_list_empty_meta(self, provider):
        """Test _get_torrent_files_list with empty metadata."""
        # Given
        meta_info = None

        # When
        files = provider._get_torrent_files_list(meta_info)

        # Then
        assert files == []

    def test_get_torrent_files_list_invalid_meta(self, provider):
        """Test _get_torrent_files_list with invalid metadata."""
        # Given
        meta_info = {b'invalid': b'data'}

        # When
        files = provider._get_torrent_files_list(meta_info)

        # Then
        assert files == []

    def test_verify_download_invalid_file(self, provider):
        """Test _verify_download with non-existent file."""
        # Given
        app.IGNORE_TORRENTS_WITH_FILE_REGEX = [r'\.exe$']

        # When
        result = provider._verify_download('/nonexistent/file.torrent')

        # Then
        assert result is False

    def test_verify_download_corrupted_file(self, provider):
        """Test _verify_download with corrupted torrent file."""
        # Given
        app.IGNORE_TORRENTS_WITH_FILE_REGEX = [r'\.exe$']

        # Create a corrupted file
        fd, path = tempfile.mkstemp(suffix='.torrent')
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(b'corrupted data')

            # When
            result = provider._verify_download(path)

            # Then
            assert result is False

        finally:
            if os.path.exists(path):
                os.remove(path)


class TestMagnetFileFiltering(object):
    """Test magnet link filtering with regex patterns."""

    @pytest.fixture
    def provider(self):
        """Create a mock torrent provider."""
        provider = TorrentProvider('TestProvider')
        provider.session = Mock()
        return provider

    def create_magnet_file(self, info_hash):
        """
        Create a magnet link file.

        :param info_hash: Info hash for the magnet link
        :return: Path to the created magnet file
        """
        magnet_uri = f'magnet:?xt=urn:btih:{info_hash}'

        fd, path = tempfile.mkstemp(suffix='.magnet')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(magnet_uri)
        except Exception:
            os.close(fd)
            raise

        return path

    @pytest.mark.parametrize('p', [
        {  # p0: No regex patterns - magnet should pass
            'info_hash': '1234567890ABCDEF1234567890ABCDEF12345678',
            'regex_patterns': [],
            'metadata_available': False,
            'expected': True
        },
        {  # p1: Metadata available with blocked file
            'info_hash': '1234567890ABCDEF1234567890ABCDEF12345678',
            'regex_patterns': [r'\.exe$'],
            'metadata_available': True,
            'files_in_metadata': ['video.mkv', 'crack.exe'],
            'expected': False
        },
        {  # p2: Metadata available without blocked file
            'info_hash': '1234567890ABCDEF1234567890ABCDEF12345678',
            'regex_patterns': [r'\.exe$'],
            'metadata_available': True,
            'files_in_metadata': ['video.mkv', 'subtitles.srt'],
            'expected': True
        },
        {  # p3: Metadata not available - magnet should pass (graceful degradation)
            'info_hash': '1234567890ABCDEF1234567890ABCDEF12345678',
            'regex_patterns': [r'\.exe$'],
            'metadata_available': False,
            'expected': True
        },
    ])
    def test_verify_magnet_with_regex_filtering(self, provider, p, app_config, caplog):
        """Test _verify_magnet with various scenarios."""
        # Given
        info_hash = p['info_hash']
        regex_patterns = p['regex_patterns']
        metadata_available = p['metadata_available']
        expected = p['expected']

        app.IGNORE_TORRENTS_WITH_FILE_REGEX = regex_patterns

        # Create magnet file
        magnet_path = self.create_magnet_file(info_hash)

        try:
            # Mock metadata fetching
            if metadata_available:
                files = p.get('files_in_metadata', [])
                # Create metadata structure
                file_list = []
                for file_name in files:
                    parts = file_name.split('/')
                    file_list.append({
                        b'path': [p.encode('utf-8') for p in parts],
                        b'length': 1024
                    })

                meta_info = {
                    b'info': {
                        b'name': b'TorrentName',
                        b'files': file_list
                    }
                }
                with patch.object(provider, '_fetch_torrent_metadata_from_magnet', return_value=meta_info):
                    # When
                    result = provider._verify_magnet(magnet_path)
            else:
                with patch.object(provider, '_fetch_torrent_metadata_from_magnet', return_value=None):
                    # When
                    result = provider._verify_magnet(magnet_path)

            # Then
            assert result == expected, \
                f"Expected {expected}, got {result} for patterns {regex_patterns}"

        finally:
            # Cleanup
            if os.path.exists(magnet_path):
                os.remove(magnet_path)

    def test_fetch_torrent_metadata_from_magnet_success(self, provider):
        """Test successful metadata fetching from magnet."""
        # Given
        magnet_uri = 'magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678'

        # Create fake torrent metadata
        meta_info = {
            b'info': {
                b'name': b'test.mkv',
                b'length': 1024
            }
        }
        torrent_data = BENCODE.encode(meta_info)

        # Mock successful response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.content = torrent_data
        provider.session.get = Mock(return_value=mock_response)

        # When
        result = provider._fetch_torrent_metadata_from_magnet(magnet_uri)

        # Then
        assert result is not None
        assert b'info' in result
        assert result[b'info'][b'name'] == b'test.mkv'

    def test_fetch_torrent_metadata_from_magnet_failure(self, provider):
        """Test failed metadata fetching from magnet."""
        # Given
        magnet_uri = 'magnet:?xt=urn:btih:1234567890ABCDEF1234567890ABCDEF12345678'

        # Mock failed response
        mock_response = Mock()
        mock_response.ok = False
        provider.session.get = Mock(return_value=mock_response)

        # When
        result = provider._fetch_torrent_metadata_from_magnet(magnet_uri)

        # Then
        assert result is None

    def test_fetch_torrent_metadata_invalid_magnet(self, provider):
        """Test metadata fetching with invalid magnet URI."""
        # Given
        invalid_magnet = 'not a magnet link'

        # When
        result = provider._fetch_torrent_metadata_from_magnet(invalid_magnet)

        # Then
        assert result is None

    def test_verify_magnet_invalid_file(self, provider):
        """Test _verify_magnet with non-existent file."""
        # Given
        app.IGNORE_TORRENTS_WITH_FILE_REGEX = [r'\.exe$']

        # When
        result = provider._verify_magnet('/nonexistent/file.magnet')

        # Then
        assert result is False

    def test_verify_magnet_invalid_hash(self, provider):
        """Test _verify_magnet with invalid info hash."""
        # Given
        app.IGNORE_TORRENTS_WITH_FILE_REGEX = []

        # Create magnet file with invalid hash
        fd, path = tempfile.mkstemp(suffix='.magnet')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write('magnet:?xt=invalid')

            # When
            result = provider._verify_magnet(path)

            # Then
            assert result is False

        finally:
            if os.path.exists(path):
                os.remove(path)
