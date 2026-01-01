"""Tests for variant_selector module."""
from __future__ import annotations

import pytest

from archive_lib.variant_selector import (
    VariantRole,
    select_variant,
    get_variant_index,
    build_variant_index,
)


def test_select_variant_prefer_ai():
    """Test variant selection preferring AI."""
    variants = [
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    result = select_variant(variants, prefer_ai=True)
    assert result is not None
    assert result['role'] == 'ai_front_v1'


def test_select_variant_prefer_original():
    """Test variant selection preferring original over AI."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        {'role': 'proxy_front', 'path': '/orig.jpg'},
    ]
    result = select_variant(variants, prefer_ai=False)
    assert result is not None
    assert result['role'] == 'proxy_front'


def test_select_variant_fallback():
    """Test variant selection with fallback when preferred not available."""
    variants = [{'role': 'proxy_front', 'path': '/proxy.jpg'}]
    result = select_variant(variants, prefer_ai=True)
    assert result is not None
    assert result['role'] == 'proxy_front'


def test_select_variant_preferred_role():
    """Test explicit preferred role override."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        {'role': 'raw_front', 'path': '/raw.jpg'},
    ]
    result = select_variant(variants, preferred_role='raw_front')
    assert result is not None
    assert result['role'] == 'raw_front'


def test_select_variant_no_variants():
    """Test that empty variant list returns None."""
    result = select_variant([], prefer_ai=True)
    assert result is None


def test_select_variant_no_matching_role():
    """Test that missing preferred role falls back to default selection."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    result = select_variant(variants, preferred_role='raw_front')
    # When preferred role not found, falls back to normal selection
    assert result is not None
    assert result['role'] == 'ai_front_v1'


def test_select_variant_invalid_role():
    """Test that variants without role are skipped."""
    variants = [
        {'path': '/no-role.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    result = select_variant(variants, prefer_ai=True)
    assert result is not None
    assert result['role'] == 'ai_front_v1'


def test_select_variant_prefer_ai_fallback_to_original():
    """Test that AI preference falls back to original when AI not available."""
    variants = [
        {'role': 'proxy_front', 'path': '/proxy.jpg'},
        {'role': 'raw_front', 'path': '/raw.jpg'},
    ]
    result = select_variant(variants, prefer_ai=True)
    assert result is not None
    # Should fallback to proxy (before raw in fallback order)
    assert result['role'] == 'proxy_front'


def test_select_variant_prefer_original_fallback_to_ai():
    """Test that original preference falls back to AI when originals not available."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    result = select_variant(variants, prefer_ai=False)
    assert result is not None
    # Should fallback to AI as last resort
    assert result['role'] == 'ai_front_v1'


def test_select_variant_is_primary():
    """Test that is_primary variants are preferred."""
    variants = [
        {'role': 'raw_front', 'path': '/raw1.jpg', 'is_primary': False},
        {'role': 'raw_front', 'path': '/raw2.jpg', 'is_primary': True},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    result = select_variant(variants, prefer_ai=False)
    assert result is not None
    # Should pick the primary raw variant
    assert result['path'] == '/raw2.jpg'


def test_get_variant_index():
    """Test get_variant_index returns correct index."""
    variants = [
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    # Prefer AI should return index 1
    assert get_variant_index(variants, prefer_ai=True) == 1
    # Prefer original should return index 0
    assert get_variant_index(variants, prefer_ai=False) == 0


def test_get_variant_index_not_found():
    """Test get_variant_index returns -1 when no variant found."""
    variants = []
    assert get_variant_index(variants, prefer_ai=True) == -1


def test_get_variant_index_with_preferred_role():
    """Test get_variant_index with explicit preferred role."""
    variants = [
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        {'role': 'proxy_front', 'path': '/proxy.jpg'},
    ]
    assert get_variant_index(variants, preferred_role='proxy_front') == 2


def test_build_variant_index():
    """Test build_variant_index creates role mapping."""
    variants = [
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    index = build_variant_index(variants)
    assert 'raw_front' in index
    assert 'ai_front_v1' in index
    assert index['raw_front']['path'] == '/raw.jpg'
    assert index['ai_front_v1']['path'] == '/ai.jpg'


def test_build_variant_index_duplicates():
    """Test that build_variant_index keeps only first of duplicate roles."""
    variants = [
        {'role': 'raw_front', 'path': '/raw1.jpg'},
        {'role': 'raw_front', 'path': '/raw2.jpg'},
    ]
    index = build_variant_index(variants)
    assert 'raw_front' in index
    # Should keep the first one
    assert index['raw_front']['path'] == '/raw1.jpg'


def test_build_variant_index_no_role():
    """Test that variants without role are skipped."""
    variants = [
        {'path': '/no-role.jpg'},
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
    ]
    index = build_variant_index(variants)
    assert 'ai_front_v1' in index
    assert len(index) == 1


def test_variant_role_enum():
    """Test VariantRole enum values."""
    assert VariantRole.AI.value == 'ai_front_v1'
    assert VariantRole.PROXY.value == 'proxy_front'
    assert VariantRole.RAW.value == 'raw_front'
    assert VariantRole.ORIGINAL.value == 'original'


def test_select_variant_raw_before_ai_when_not_prefer_ai():
    """Test selection order when not preferring AI."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'proxy_front', 'path': '/proxy.jpg'},
    ]
    result = select_variant(variants, prefer_ai=False)
    assert result is not None
    # Should prefer proxy over raw over AI
    assert result['role'] == 'proxy_front'


def test_select_variant_ai_before_proxy_when_prefer_ai():
    """Test selection order when preferring AI."""
    variants = [
        {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        {'role': 'raw_front', 'path': '/raw.jpg'},
        {'role': 'proxy_front', 'path': '/proxy.jpg'},
    ]
    result = select_variant(variants, prefer_ai=True)
    assert result is not None
    # Should prefer AI first
    assert result['role'] == 'ai_front_v1'
