#!/usr/bin/env python3
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from pinterest_board_dl import parse_pin_count


def test_parse_pin_count():
    print("Testing parse_pin_count...")

    test_cases = [
        ("10", 10),
        ("10 pins", 10),
        ("1 pin", 1),
        ("1,2 mil", 1200),
        ("1.2k", 1200),
        ("2.5m", 2500000),
        ("3,4 mi", 3400000),
        (",15", 15),
        ("15,", 15),
        ("", None),
        ("abc", None),
        ("1.000 pins", 1000),
    ]

    for input_str, expected in test_cases:
        result = parse_pin_count(input_str)
        assert result == expected, f"Failed for '{input_str}': expected {expected}, got {result}"
        print(f"  ✓ '{input_str}' -> {result}")


if __name__ == "__main__":
    try:
        test_parse_pin_count()
        print("\n✅ All parse tests passed!")
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
