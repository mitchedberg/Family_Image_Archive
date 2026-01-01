"""Unit tests for the centralized filename_parser module."""
import pytest

from photo_archive.archive_lib.filename_parser import (
    ParsedTokens,
    extract_fastfoto_token,
    extract_hex_tokens,
    extract_img_token,
    extract_pro4k_token,
    extract_uuid,
    parse_filename,
)


class TestExtractFastfotoToken:
    """Test cases for extract_fastfoto_token function."""

    def test_basic_fastfoto_token(self):
        assert extract_fastfoto_token("FastFoto123_image.jpg") == "123"

    def test_lowercase_with_underscore(self):
        assert extract_fastfoto_token("fastfoto_001234.tif") == "001234"

    def test_uppercase_with_dash(self):
        assert extract_fastfoto_token("FASTFOTO-4567.jpg") == "4567"

    def test_case_insensitive(self):
        assert extract_fastfoto_token("fAsTfOtO_999.jpg") == "999"

    def test_no_token(self):
        assert extract_fastfoto_token("no_token.jpg") is None

    def test_none_input(self):
        assert extract_fastfoto_token(None) is None

    def test_empty_string(self):
        assert extract_fastfoto_token("") is None

    def test_three_digit_minimum(self):
        assert extract_fastfoto_token("fastfoto_100.jpg") == "100"

    def test_six_digit_maximum(self):
        assert extract_fastfoto_token("fastfoto_123456.jpg") == "123456"

    def test_token_in_middle(self):
        assert extract_fastfoto_token("prefix_FastFoto999_suffix.tif") == "999"


class TestExtractImgToken:
    """Test cases for extract_img_token function.

    Note: IMG_ID_RE expects format like IMG20230101_1234 or IMG20230101-1234
    (8 digits directly after IMG, then optional separator, then 4+ more digits)
    """

    def test_basic_img_token(self):
        # Format: IMG + 8 digits + separator + 4+ digits
        result = extract_img_token("IMG20230101_1234.jpg")
        assert result == "img20230101_1234"

    def test_underscore_variant(self):
        result = extract_img_token("IMG12345678_9876.jpg")
        assert result is not None
        assert "img" in result
        assert "12345678" in result

    def test_dash_converted_to_underscore(self):
        result = extract_img_token("IMG20230101-5678.jpg")
        assert result is not None
        assert "_" in result
        assert "-" not in result

    def test_double_underscore_suffix(self):
        result = extract_img_token("IMG12345678_5678__001.jpg")
        assert result is not None
        assert "__001" in result

    def test_parenthesis_suffix(self):
        result = extract_img_token("IMG12345678_9999(2).jpg")
        assert result is not None
        assert "__2" in result

    def test_no_token(self):
        assert extract_img_token("no_img_here.jpg") is None

    def test_none_input(self):
        assert extract_img_token(None) is None

    def test_empty_string(self):
        assert extract_img_token("") is None

    def test_case_insensitive(self):
        result = extract_img_token("img20230101_1234.jpg")
        assert result is not None

    def test_in_path(self):
        result = extract_img_token("/path/to/IMG20230101_1234.jpg")
        assert result is not None

    def test_no_separator(self):
        # Must have at least 12 consecutive digits (8 + 4)
        result = extract_img_token("IMG202301011234.jpg")
        assert result is not None


class TestExtractHexTokens:
    """Test cases for extract_hex_tokens function.

    Note: HEX_RE uses word boundaries, so hex tokens must be separated by
    non-word characters (spaces, dots) not underscores which are word chars.
    """

    def test_single_hex_token_with_spaces(self):
        tokens = extract_hex_tokens("image a1b2c3d4 photo.jpg")
        assert "a1b2c3d4" in tokens

    def test_hex_at_start(self):
        tokens = extract_hex_tokens("a1b2c3d4 image.jpg")
        assert "a1b2c3d4" in tokens

    def test_hex_at_end(self):
        tokens = extract_hex_tokens("image.a1b2c3d4")
        assert "a1b2c3d4" in tokens

    def test_multiple_hex_tokens_with_spaces(self):
        # Note: need non-hex chars to create word boundaries
        tokens = extract_hex_tokens("1234abcd 5678ef90 photo.tif")
        assert "1234abcd" in tokens
        assert "5678ef90" in tokens

    def test_no_hex_tokens(self):
        tokens = extract_hex_tokens("no_hex_here.jpg")
        assert tokens == []

    def test_case_normalized_to_lowercase(self):
        tokens = extract_hex_tokens("ABC12345 file")
        assert "abc12345" in tokens

    def test_eight_char_minimum(self):
        tokens = extract_hex_tokens("abcd1234 file")
        assert "abcd1234" in tokens

    def test_sixteen_char_maximum(self):
        tokens = extract_hex_tokens("0123456789abcdef file")
        assert "0123456789abcdef" in tokens

    def test_seventeen_char_excluded(self):
        # Tokens longer than 16 characters should not match
        tokens = extract_hex_tokens("0123456789abcdef0 file")
        # The 17-char token shouldn't match the 8-16 char pattern
        assert len([t for t in tokens if len(t) == 17]) == 0

    def test_seven_char_excluded(self):
        # Tokens shorter than 8 characters should not match
        tokens = extract_hex_tokens("abcd123 file")
        assert len([t for t in tokens if len(t) == 7]) == 0

    def test_dot_separator(self):
        tokens = extract_hex_tokens("prefix.a1b2c3d4.suffix")
        assert "a1b2c3d4" in tokens


class TestExtractPro4kToken:
    """Test cases for extract_pro4k_token function."""

    def test_basic_pro4k_token(self):
        assert extract_pro4k_token("image_pro4k_123.jpg") == "123"

    def test_uppercase(self):
        assert extract_pro4k_token("photo_PRO4K_456.png") == "456"

    def test_with_dash(self):
        assert extract_pro4k_token("photo_PRO-4K-789.jpg") == "789"

    def test_with_underscore(self):
        assert extract_pro4k_token("image_pro_4k_001.jpg") == "001"

    def test_no_token(self):
        assert extract_pro4k_token("no_pro4k.jpg") is None

    def test_case_insensitive(self):
        assert extract_pro4k_token("PrO4K_999.jpg") == "999"

    def test_no_separator(self):
        assert extract_pro4k_token("pro4k123.jpg") == "123"


class TestExtractUuid:
    """Test cases for extract_uuid function."""

    def test_basic_uuid(self):
        result = extract_uuid("550e8400-e29b-41d4-a716-446655440000.jpg")
        assert result == "550e8400_e29b_41d4_a716_446655440000"

    def test_uppercase_normalized(self):
        result = extract_uuid("550E8400-E29B-41D4-A716-446655440000.jpg")
        assert result == "550e8400_e29b_41d4_a716_446655440000"

    def test_dashes_converted_to_underscores(self):
        result = extract_uuid("550e8400-e29b-41d4-a716-446655440000.jpg")
        assert "_" in result
        assert "-" not in result

    def test_no_uuid(self):
        assert extract_uuid("no_uuid.jpg") is None

    def test_none_input(self):
        assert extract_uuid(None) is None

    def test_empty_string(self):
        assert extract_uuid("") is None

    def test_invalid_format(self):
        # Not a valid UUID format
        assert extract_uuid("123-456-789.jpg") is None


class TestParseFilename:
    """Test cases for parse_filename function."""

    def test_all_tokens(self):
        # Use proper IMG format: IMG + 8 digits + separator + 4+ digits
        result = parse_filename("FastFoto123 IMG20230101_5678 a1b2c3d4 pro4k_001.jpg")
        assert result.fastfoto_id == "123"
        assert result.img_id is not None
        assert "img" in result.img_id.lower()
        assert "a1b2c3d4" in result.hex_tokens
        assert result.pro4k_id == "001"

    def test_fastfoto_only(self):
        result = parse_filename("FastFoto999.jpg")
        assert result.fastfoto_id == "999"
        assert result.img_id is None
        assert result.hex_tokens == []
        assert result.pro4k_id is None

    def test_img_only(self):
        result = parse_filename("IMG20230101_1234.jpg")
        assert result.fastfoto_id is None
        assert result.img_id is not None
        assert result.hex_tokens == []
        assert result.pro4k_id is None

    def test_hex_only(self):
        result = parse_filename("image abc12345.jpg")
        assert result.fastfoto_id is None
        assert result.img_id is None
        assert "abc12345" in result.hex_tokens
        assert result.pro4k_id is None

    def test_pro4k_only(self):
        result = parse_filename("image_pro4k_789.jpg")
        assert result.fastfoto_id is None
        assert result.img_id is None
        assert result.pro4k_id == "789"

    def test_no_tokens(self):
        result = parse_filename("simple_image.jpg")
        assert result.fastfoto_id is None
        assert result.img_id is None
        assert result.hex_tokens == []
        assert result.pro4k_id is None
        assert result.uuid is None

    def test_uuid_token(self):
        result = parse_filename("550e8400-e29b-41d4-a716-446655440000.jpg")
        assert result.uuid == "550e8400_e29b_41d4_a716_446655440000"

    def test_parsed_tokens_dataclass(self):
        result = parse_filename("test.jpg")
        assert isinstance(result, ParsedTokens)
        assert hasattr(result, "fastfoto_id")
        assert hasattr(result, "img_id")
        assert hasattr(result, "hex_tokens")
        assert hasattr(result, "pro4k_id")
        assert hasattr(result, "uuid")


class TestComplexScenarios:
    """Test cases for complex real-world filename scenarios."""

    def test_fastfoto_with_variants(self):
        result = parse_filename("FastFoto12345 IMG20230515_1234__001 back.tif")
        assert result.fastfoto_id == "12345"
        assert result.img_id is not None
        assert "__001" in result.img_id

    def test_ai_enhanced_with_hex(self):
        result = parse_filename("a1b2c3d4 pro4k_555 enhanced.jpg")
        assert "a1b2c3d4" in result.hex_tokens
        assert result.pro4k_id == "555"

    def test_path_with_img_token(self):
        # Test that extract_img_token works with full paths (used in assigner.py)
        img_token = extract_img_token("/some/path/IMG20230101_1234.jpg")
        assert img_token is not None

    def test_multiple_hex_in_filename(self):
        # Need word boundaries between hex tokens (spaces or dots)
        result = parse_filename("12345678 abcdef00 original.tif")
        assert len(result.hex_tokens) == 2
        assert "12345678" in result.hex_tokens
        assert "abcdef00" in result.hex_tokens

    def test_case_mixed_tokens(self):
        result = parse_filename("FASTFOTO999 img20230101_5678 ABC12345.JPG")
        assert result.fastfoto_id == "999"
        assert result.img_id is not None
        assert "abc12345" in result.hex_tokens


class TestRealWorldExamples:
    """Test cases based on actual filename patterns from the codebase."""

    def test_bucket_prefix_extraction(self):
        """Bucket prefixes are 12-char hex tokens used for matching."""
        # Simulating a filename with bucket prefix
        tokens = extract_hex_tokens("prefix.a1b2c3d4e5f6.jpg")
        assert "a1b2c3d4e5f6" in tokens

    def test_img_token_with_double_underscore_suffix(self):
        """Real-world IMG tokens from Photos.app export."""
        result = extract_img_token("IMG20210315_123456__001.jpg")
        assert result is not None
        assert "img20210315_123456__001" == result

    def test_img_token_with_paren_suffix(self):
        """IMG tokens with parenthesis suffix get normalized."""
        result = extract_img_token("IMG20210315_123456(3).jpg")
        assert result is not None
        assert "__3" in result

    def test_fastfoto_in_group_key(self):
        """FastFoto tokens are used to create group keys."""
        token = extract_fastfoto_token("some_dir/FastFoto123_scan.tif")
        assert token == "123"
        # Group key would be: f"fastfoto_{token}"

    def test_pro4k_ai_enhancement(self):
        """PRO4K tokens identify AI-enhanced images."""
        token = extract_pro4k_token("IMG20210101_1234_pro4k_100.jpg")
        assert token == "100"
