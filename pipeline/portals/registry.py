"""Which billing portal serves which town."""
from .hls import HlsPortal
from .wipp import WippPortal

TOWNS = {
    "jersey-city": {"county_district": "0906", "name": "Jersey City", "make": lambda s: HlsPortal("JerseyCity", "0906", s)},
    # Hoboken also has an HLS page, but it carries no bill data; live bills are on WIPP.
    "hoboken": {"county_district": "0905", "name": "Hoboken", "make": lambda s: WippPortal("0905", session=s)},
    "union-city": {"county_district": "0910", "name": "Union City", "make": lambda s: WippPortal("0910", session=s)},
}


def portal_for(town, session):
    return TOWNS[town]["make"](session)
