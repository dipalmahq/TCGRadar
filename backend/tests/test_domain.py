from dataclasses import replace
import pytest

from app.adapters.base import SourceOffer
from app.domain import classify, valid_gtin


def source(title="One Piece OP-17 Display 24 Booster [ENG]", **kwargs):
    return SourceOffer(external_id="1", title=title, url="https://fixture.example/products/one-piece", price_minor=12999, currency="EUR", availability="in_stock", **kwargs)


def test_exact_product_can_match_across_merchants():
    a = classify(source(), "a")
    b = classify(source("One Piece Card Game OP17 Booster Box 24 Packs English"), "b")
    assert a.identity_key == b.identity_key
    assert a.confidence == "exact_attributes"


@pytest.mark.parametrize("title", ["One Piece OP17 Display 24 Booster Deutsch", "One Piece OP17 Booster [ENG]", "One Piece OP17 Display 12 Booster [ENG]", "One Piece OP17 Enhanced Display 24 Booster [ENG]"])
def test_different_variants_never_merge(title):
    assert classify(source(), "a").identity_key != classify(source(title), "b").identity_key


@pytest.mark.parametrize("title", ["One Piece OP17 Display [ENG]", "One Piece OP17 Display 24 Booster", "Pokemon Testset Display 36 Booster Deutsch"])
def test_uncertain_products_stay_separate(title):
    assert classify(source(title), "a").identity_key != classify(source(title), "b").identity_key


def test_variant_type_overrides_parent_display_title():
    item = source("Pokemon Testset Booster Display · Booster", variant_label="Booster", language_hint="Deutsch", description="Display enthält 36 Booster")
    result = classify(item, "a")
    assert (result.product_type, result.booster_count) == ("booster", 1)


def test_mixed_category_does_not_turn_an_ambiguous_display_into_a_booster():
    item = source("Dragon Ball Super Fusion World New Adventure FB05", labels="Englisch Dragon Ball Booster & Displays", description="Dragon Ball Super Fusion World FB05 – Display (englisch) enthält: 24 Booster Packs mit je 12 Karten")
    result = classify(item, "a")
    assert result.product_type == "display"
    assert result.booster_count == 24
    assert classify(replace(item, description=""), "a") is None


def test_fusion_world_is_distinct_from_masters():
    result = classify(source("Dragon Ball Super Fusion World FB11 Display 24 Booster ENG"), "a")
    assert result.game == "dragon-ball-fusion-world"
    masters = classify(source("Dragon Ball Super Masters B31 Booster Display English"), "a")
    assert masters.game == "dragon-ball-masters" and masters.set_code == "B-31"


@pytest.mark.parametrize("title", ["One Piece OP17-001 Leader [ENG]", "Pokemon Sleeves Booster Design", "Pokemon Mystery Booster Box", "One Piece OP17 Display opened [ENG]", "The Acrylic Box Booster Box Pokemon 36 Booster Display Acrylcase", "Pokemon Top Trainer Box Acrylcase"])
def test_accessories_singles_and_open_products_are_excluded(title):
    assert classify(source(title), "a") is None


def test_gtin_checksum_and_unknown_language():
    assert valid_gtin("4006381333931") == "04006381333931"
    assert valid_gtin("4006381333932") is None
    a = source("Pokemon Testset Display", gtin="4006381333931")
    assert classify(a, "a").confidence == "isolated"
    assert classify(replace(a, language_hint="Deutsch"), "a").confidence == "gtin"


def test_case_does_not_use_inner_box_count_as_total_boosters():
    result = classify(source("One Piece OP17 Case ENG", description="12 Booster Boxes mit je 24 Booster Packs"), "a")
    assert result.product_type == "case" and result.booster_count is None
    total = classify(source("One Piece OP17 Case ENG", description="Insgesamt 288 Booster Packs"), "a")
    assert total.booster_count == 288


def test_multi_booster_is_not_mistaken_for_one_pack_or_set_number():
    bundle = classify(source("Pokemon Testset 3 Booster DE"), "a")
    assert (bundle.product_type, bundle.booster_count) == ("bundle", 3)
    single = classify(source("One Piece OP-17 Booster ENG"), "a")
    assert single.booster_count == 1


def test_repeated_component_counts_are_not_assumed_to_be_total():
    item = source("Pokemon Test Kollektion DE", description="3 Booster aus Set A und 3 Booster aus Set B")
    assert classify(item, "a").booster_count is None


def test_pokemon_151_set_number_is_not_a_pack_quantity():
    single = classify(source("Pokemon 151 Booster Japanisch"), "a")
    assert (single.product_type, single.booster_count) == ("booster", 1)
    display = classify(source("Pokemon 151 Booster Display Englisch"), "a")
    assert display.booster_count is None


def test_bundle_and_tin_displays_require_explicit_total_pack_count():
    bundle = source("Scarlet & Violet Pokemon 151 Booster Bundle Display Englisch", description="10 Pokemon Scarlet & Violet 151 Booster Bundle. Jedes Bundle enthält 6 Booster.")
    assert classify(bundle, "a").booster_count is None
    assert classify(replace(bundle, description="Insgesamt 60 Booster Packs"), "a").booster_count == 60
    assert classify(source("Pokemon Test Mini Tin Display Deutsch", description="10 Tins mit je 2 Booster Packs"), "a").booster_count is None
