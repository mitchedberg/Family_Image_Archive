"""Centralized variant selection utility for choosing between AI, PROXY, RAW versions.

This module provides a unified interface for selecting the best variant from
available bucket variants based on preference hierarchy and role availability.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional


class VariantRole(Enum):
    """Standard variant roles."""
    AI = 'ai_front_v1'
    PROXY = 'proxy_front'
    RAW = 'raw_front'
    ORIGINAL = 'original'


def select_variant(
    variants: List[Dict],
    prefer_ai: bool = True,
    preferred_role: Optional[str] = None
) -> Optional[Dict]:
    """Select best variant from available variants.

    Args:
        variants: List of variant dicts with 'role' key
        prefer_ai: If True, prefer AI over ORIGINAL/PROXY/RAW
        preferred_role: Override to force specific role

    Returns:
        Selected variant dict, or None if no suitable variant

    Selection logic:
        1. If preferred_role specified, use that (if available)
        2. Else if prefer_ai: AI → PROXY → RAW
        3. Else: PROXY → RAW → AI (fallback)

    Examples:
        >>> variants = [
        ...     {'role': 'raw_front', 'path': '/raw.jpg'},
        ...     {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        ... ]
        >>> result = select_variant(variants, prefer_ai=True)
        >>> result['role']
        'ai_front_v1'

        >>> result = select_variant(variants, prefer_ai=False)
        >>> result['role']
        'raw_front'

        >>> result = select_variant(variants, preferred_role='raw_front')
        >>> result['role']
        'raw_front'
    """
    if not variants:
        return None

    # Build role → variant mapping, preferring primary variants
    role_map: Dict[str, Dict] = {}
    for variant in variants:
        role = variant.get("role")
        if not role:
            continue
        # Prefer primary variants if multiple with same role exist
        if role not in role_map or variant.get("is_primary"):
            role_map[role] = variant

    # Handle explicit preferred role override
    if preferred_role and preferred_role in role_map:
        return role_map[preferred_role]

    # Define selection order based on preference
    if prefer_ai:
        order = [VariantRole.AI.value, VariantRole.PROXY.value, VariantRole.RAW.value]
    else:
        # When not preferring AI, check originals first, then AI as fallback
        order = [VariantRole.PROXY.value, VariantRole.RAW.value, VariantRole.AI.value]

    # Try roles in order
    for role in order:
        variant = role_map.get(role)
        if variant:
            return variant

    # No preferred variants found, return None
    return None


def get_variant_index(
    variants: List[Dict],
    prefer_ai: bool = True,
    preferred_role: Optional[str] = None
) -> int:
    """Get index of selected variant.

    Args:
        variants: List of variant dicts with 'role' key
        prefer_ai: If True, prefer AI over ORIGINAL/PROXY/RAW
        preferred_role: Override to force specific role

    Returns:
        Index in variants list, or -1 if none found.

    Examples:
        >>> variants = [
        ...     {'role': 'raw_front', 'path': '/raw.jpg'},
        ...     {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        ... ]
        >>> get_variant_index(variants, prefer_ai=True)
        1
        >>> get_variant_index(variants, prefer_ai=False)
        0
    """
    selected = select_variant(variants, prefer_ai, preferred_role)
    if selected is None:
        return -1

    try:
        return variants.index(selected)
    except ValueError:
        return -1


def build_variant_index(variants: List[Dict]) -> Dict[str, Dict]:
    """Build a role → variant mapping from a list of variants.

    This is a helper function that creates a dictionary mapping variant roles
    to their variant dictionaries. If multiple variants have the same role,
    only the first is kept in the mapping.

    Args:
        variants: List of variant dicts with 'role' key

    Returns:
        Dictionary mapping role strings to variant dicts

    Examples:
        >>> variants = [
        ...     {'role': 'raw_front', 'path': '/raw.jpg'},
        ...     {'role': 'ai_front_v1', 'path': '/ai.jpg'},
        ... ]
        >>> index = build_variant_index(variants)
        >>> 'raw_front' in index
        True
        >>> index['ai_front_v1']['path']
        '/ai.jpg'
    """
    index: Dict[str, Dict] = {}
    for variant in variants:
        role = variant.get("role")
        if role and role not in index:
            index[role] = variant
    return index
