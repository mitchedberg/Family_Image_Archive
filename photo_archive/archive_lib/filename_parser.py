"""Centralized filename parsing module for extracting tokens from filenames.

This module consolidates all filename token parsing logic to provide a single
source of truth for regex patterns and token extraction functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# ============================================================================
# Regex Patterns
# ============================================================================

# FastPhoto ID pattern - matches "FastPhoto123" or "fastfoto_1234"
# Examples: FastFoto123, fastfoto_001234, FASTFOTO-4567
FASTFOTO_ID_RE = re.compile(r"(?i)fastfoto[_-]?(\d{3,6})")

# IMG ID pattern - matches standard camera image IDs
# Examples: IMG20230101_1234, img_12345678_9876
IMG_ID_RE = re.compile(r"(?i)(img\d{8}[_-]?\d{4,})")

# IMG suffix patterns for duplicate/variant detection
# Double underscore suffix: IMG_1234__001
IMG_SUFFIX_DBLUND_RE = re.compile(r"__([0-9]+)")
# Parenthesis suffix: IMG_1234(1)
IMG_SUFFIX_PAREN_RE = re.compile(r"\(([0-9]+)\)")

# Hex prefix pattern - matches hex strings 8-64 characters long
# Examples: a1b2c3d4, 1234567890abcdef
HEX_PREFIX_RE = re.compile(r"(?i)\b[a-f0-9]{8,64}\b")

# Hex pattern for shorter hex tokens (8-16 characters)
# Used in pending.py for token extraction
# Examples: abc12345, 1a2b3c4d
HEX_RE = re.compile(r"\b[0-9a-f]{8,16}\b", re.IGNORECASE)

# UUID pattern - matches standard UUID format
# Example: 550e8400-e29b-41d4-a716-446655440000
UUID_RE = re.compile(
    r"(?i)([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})"
)

# PRO4K pattern - matches AI enhancement tokens
# Examples: pro4k_123, PRO_4K-456, pro4k789
PRO4K_RE = re.compile(r"pro[_-]?4k[_-]?(\d+)", re.IGNORECASE)


# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class ParsedTokens:
    """Tokens extracted from a filename.

    This dataclass holds all the different types of tokens that can be
    extracted from a filename, making it easy to access and extend.
    """

    fastfoto_id: Optional[str] = None
    img_id: Optional[str] = None
    hex_tokens: List[str] = field(default_factory=list)
    pro4k_id: Optional[str] = None
    uuid: Optional[str] = None


# ============================================================================
# Token Extraction Functions
# ============================================================================


def extract_fastfoto_token(filename: Optional[str]) -> Optional[str]:
    """Extract FastPhoto ID token from a filename.

    Args:
        filename: The filename to parse (can be None)

    Returns:
        The numeric portion of the FastPhoto ID if found, otherwise None

    Examples:
        >>> extract_fastfoto_token('FastFoto123_image.jpg')
        '123'
        >>> extract_fastfoto_token('fastfoto_001234.tif')
        '001234'
        >>> extract_fastfoto_token('no_token.jpg')
        None
    """
    if not filename:
        return None
    match = FASTFOTO_ID_RE.search(filename)
    if match:
        return match.group(1)
    return None


def extract_img_token(value: Optional[str]) -> Optional[str]:
    """Extract IMG ID token from a filename or path.

    This function extracts standard camera IMG tokens and normalizes them,
    including handling duplicate/variant suffixes.

    Args:
        value: The filename or path to parse (can be None)

    Returns:
        The normalized IMG token with any suffix, or None if not found

    Examples:
        >>> extract_img_token('IMG_20230101_1234.jpg')
        'img20230101_1234'
        >>> extract_img_token('IMG_5678__001.jpg')
        'img_5678__001'
        >>> extract_img_token('IMG_9999(2).jpg')
        'img_9999__2'
        >>> extract_img_token('no_img_here.jpg')
        None
    """
    if not value:
        return None
    value_lower = value.lower()
    match = IMG_ID_RE.search(value_lower)
    if not match:
        return None

    # Normalize the token by replacing dashes with underscores
    token = match.group(1).lower().replace("-", "_")
    suffix = None

    # Check for suffix patterns after the main IMG token
    start = match.end()
    tail = value_lower[start:]
    if tail:
        # Look for double underscore suffix first
        dbl = IMG_SUFFIX_DBLUND_RE.search(tail)
        if dbl:
            suffix = dbl.group(1)
        else:
            # Fall back to parenthesis suffix
            paren = IMG_SUFFIX_PAREN_RE.search(tail)
            if paren:
                suffix = paren.group(1)

    # Append suffix if found, normalizing to double underscore format
    if suffix:
        token = f"{token}__{suffix}"

    return token


def extract_hex_tokens(filename: str) -> List[str]:
    """Extract all hex tokens from a filename.

    Args:
        filename: The filename to parse

    Returns:
        List of lowercase hex tokens found (8-16 characters each)

    Examples:
        >>> extract_hex_tokens('image_a1b2c3d4_photo.jpg')
        ['a1b2c3d4']
        >>> extract_hex_tokens('1234abcd_5678efgh.tif')
        ['1234abcd', '5678efgh']
        >>> extract_hex_tokens('no_hex_here.jpg')
        []
    """
    lower = filename.lower()
    return [token.lower() for token in HEX_RE.findall(lower)]


def extract_pro4k_token(filename: str) -> Optional[str]:
    """Extract PRO4K AI enhancement token from a filename.

    Args:
        filename: The filename to parse

    Returns:
        The numeric portion of the PRO4K token if found, otherwise None

    Examples:
        >>> extract_pro4k_token('image_pro4k_123.jpg')
        '123'
        >>> extract_pro4k_token('photo_PRO_4K-456.png')
        '456'
        >>> extract_pro4k_token('no_pro4k.jpg')
        None
    """
    lower = filename.lower()
    match = PRO4K_RE.search(lower)
    if match:
        return match.group(1)
    return None


def extract_uuid(filename: Optional[str]) -> Optional[str]:
    """Extract UUID from a filename.

    Args:
        filename: The filename to parse (can be None)

    Returns:
        The normalized UUID (lowercase with underscores) if found, otherwise None

    Examples:
        >>> extract_uuid('550e8400-e29b-41d4-a716-446655440000.jpg')
        '550e8400_e29b_41d4_a716_446655440000'
        >>> extract_uuid('no_uuid.jpg')
        None
    """
    if not filename:
        return None
    match = UUID_RE.search(filename)
    if match:
        return match.group(1).lower().replace("-", "_")
    return None


def parse_filename(filename: str) -> ParsedTokens:
    """Extract all known tokens from a filename.

    This is a convenience function that runs all token extractors and
    returns a ParsedTokens object with all found tokens.

    Args:
        filename: The filename to parse

    Returns:
        ParsedTokens object containing all extracted tokens

    Example:
        >>> tokens = parse_filename('FastFoto123_IMG_5678_a1b2c3d4_pro4k_001.jpg')
        >>> tokens.fastfoto_id
        '123'
        >>> tokens.img_id
        'img_5678'
        >>> tokens.hex_tokens
        ['a1b2c3d4']
        >>> tokens.pro4k_id
        '001'
    """
    return ParsedTokens(
        fastfoto_id=extract_fastfoto_token(filename),
        img_id=extract_img_token(filename),
        hex_tokens=extract_hex_tokens(filename),
        pro4k_id=extract_pro4k_token(filename),
        uuid=extract_uuid(filename),
    )
