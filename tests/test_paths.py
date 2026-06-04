from paths import normalize, overlaps, any_overlap


def test_normalize_strips_slashes_and_space():
    assert normalize("  payment/ ") == "payment"
    assert normalize("/api/order.ts/") == "api/order.ts"


def test_overlaps_equal():
    assert overlaps("api/order.ts", "api/order.ts") is True


def test_overlaps_dir_is_ancestor_of_file():
    assert overlaps("payment/", "payment/refund.ts") is True
    assert overlaps("payment/refund.ts", "payment") is True


def test_overlaps_sibling_prefix_does_not_overlap():
    # "payment" must NOT be treated as a prefix of "payment2"
    assert overlaps("payment", "payment2") is False


def test_any_overlap_disjoint_false():
    assert any_overlap(["ui/cart.tsx"], ["payment/", "api/order.ts"]) is False


def test_any_overlap_intersecting_true():
    assert any_overlap(["payment/refund.ts"], ["payment/", "api/order.ts"]) is True
