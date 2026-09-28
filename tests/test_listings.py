import json
import unittest

from wa_scout.listings import Listing, dedupe, matches_criteria, normalise_type, parse_area, parse_price
from wa_scout.sources import domain_api
from wa_scout.sources.extract import listings_from_html


class ParseTests(unittest.TestCase):
    def test_prices(self):
        self.assertEqual(parse_price("Offers over $650,000"), 650_000)
        self.assertEqual(parse_price("$600k - $640k"), 620_000)
        self.assertEqual(parse_price("From $1.2m"), 1_200_000)
        self.assertEqual(parse_price("$599,000 - $629,000"), 614_000)
        self.assertIsNone(parse_price("Contact agent"))
        self.assertIsNone(parse_price("4 bed home, $650 per week"))

    def test_area_and_types(self):
        self.assertEqual(parse_area("650m²"), 650)
        self.assertEqual(parse_area("0.2 ha"), 2000)
        self.assertEqual(normalise_type("ApartmentUnitFlat"), "apartment")
        self.assertEqual(normalise_type("Townhouse"), "townhouse")
        self.assertEqual(normalise_type("Semi-Detached"), "duplex")


class CriteriaTests(unittest.TestCase):
    crit = {"property_types": ["house"], "bedrooms_min": 3, "car_spaces_min": 1,
            "metro_postcodes": [[6000, 6199], [6207, 6214]], "price_max": 700_000}

    def test_filters(self):
        ok = Listing(id="a", suburb="Midland", postcode="6056", property_type="house", price=600_000, bedrooms=3, car_spaces=2)
        self.assertTrue(matches_criteria(ok, self.crit)[0])
        regional = Listing(id="b", suburb="Bunbury", postcode="6230", property_type="house", price=500_000, bedrooms=3)
        self.assertFalse(matches_criteria(regional, self.crit)[0])
        small = Listing(id="c", suburb="Midland", postcode="6056", property_type="house", price=500_000, bedrooms=2)
        self.assertFalse(matches_criteria(small, self.crit)[0])
        dear = Listing(id="d", suburb="Midland", postcode="6056", property_type="house", price=800_000, bedrooms=4)
        self.assertFalse(matches_criteria(dear, self.crit)[0])

    def test_dedupe_merges(self):
        a = Listing(id="1", address="1 A St", suburb="Midland", price=500_000)
        b = Listing(id="2", address="1 A St", suburb="Midland", land_size_sqm=600)
        merged = dedupe([a, b])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].land_size_sqm, 600)


REA_ITEM = {
    "id": "145000001",
    "address": {"display": {"shortAddress": "12 Example Street"}, "suburb": "Midland", "state": "wa", "postcode": "6056"},
    "price": {"display": "Offers over $549,000"},
    "propertyType": {"id": "house", "display": "House"},
    "generalFeatures": {"bedrooms": {"value": 4}, "bathrooms": {"value": 2}, "parkingSpaces": {"value": 2}},
    "propertySizes": {"land": {"displayValue": "620", "sizeUnit": {"displayValue": "m²"}}},
    "_links": {"canonical": {"href": "https://www.realestate.com.au/property-house-wa-midland-145000001"}},
}


class ExtractTests(unittest.TestCase):
    def test_argonaut_nested_json_strings(self):
        inner = json.dumps({"data": json.dumps({"buySearch": {"results": {"exact": {"items": [{"listing": REA_ITEM}]}}}})})
        html = "<html><script>window.ArgonautExchange=" + json.dumps({"resi": {"urqlClientCache": inner}}) + ";</script></html>"
        found = listings_from_html(html)
        self.assertEqual(len(found), 1)
        l = found[0]
        self.assertEqual((l.suburb, l.postcode, l.bedrooms, l.bathrooms, l.car_spaces), ("Midland", "6056", 4, 2, 2))
        self.assertEqual(l.price, 549_000)
        self.assertEqual(l.land_size_sqm, 620)
        self.assertEqual(l.state, "WA")

    def test_domain_api_mapping(self):
        item = {"type": "PropertyListing", "listing": {
            "id": 2019, "listingSlug": "5-test-rd-gosnells-wa-6110-2019", "headline": "Leased at $600 pw",
            "priceDetails": {"displayPrice": "$520,000 - $560,000"},
            "propertyDetails": {"state": "WA", "propertyType": "House", "allPropertyTypes": ["House"], "bedrooms": 3,
                                "bathrooms": 1, "carspaces": 2, "landArea": 700, "displayableAddress": "5 Test Rd",
                                "suburb": "GOSNELLS", "postcode": "6110"}}}
        l = domain_api._to_listing(item)
        self.assertEqual(l.price, 540_000)
        self.assertEqual(l.suburb, "Gosnells")
        self.assertEqual(l.property_type, "house")
        self.assertIn("domain.com.au/5-test-rd", l.url)


if __name__ == "__main__":
    unittest.main()


class ReiwaTests(unittest.TestCase):
    CARD = (
        '<article class="p-card -Residential"><a href="/2-example-place-maddington-5039548/" class="p-card__details">'
        '<p class="heading h4 sk-item">From $739,000</p><h2 class="-regular p-details__add sk-item ">2 Example Place, Maddington</h2>'
        '<ul><li><svg><path/></svg><span class="u-grey-dark">3</span></li><li><span class="u-grey-dark">2</span></li>'
        '<li><span class="u-grey-dark">1</span></li><li><div class="grey-pill sk-hide">New</div><div class="grey-pill sk-hide">House</div></li></ul>'
        '<span>Added 4 days ago</span></a></article>'
    )

    def test_parse_card(self):
        from wa_scout.sources import reiwa

        (l,) = reiwa.parse_cards(self.CARD)
        self.assertEqual((l.address, l.suburb, l.price, l.bedrooms, l.bathrooms, l.car_spaces, l.property_type, l.days_on_market),
                         ("2 Example Place", "Maddington", 739_000, 3, 2, 1, "house", 4))
        self.assertTrue(l.url.endswith("-5039548/"))

    def test_listing_data_and_distance(self):
        import html as h

        from wa_scout.sources import reiwa

        data = {"data": {"ListingNo": 1, "LandsizeHtml": "491m<sup>2</sup>", "IsUnderOffer": True}}
        page = "<div data-props='" + h.escape(json.dumps(data), quote=False).replace("'", "&#39;") + "'></div>"
        self.assertEqual(reiwa.listing_data(page)["LandsizeHtml"], "491m<sup>2</sup>")
        self.assertAlmostEqual(reiwa.distance_km(-32.0458, 116.0088), 17.4, delta=0.3)
