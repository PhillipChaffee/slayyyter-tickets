from monitor.bootstrap import matches_venue


def test_matches_venue_exact():
    assert matches_venue("The Regency Ballroom", "The Regency Ballroom", "San Francisco")


def test_matches_venue_partial_name():
    # TM and SG sometimes append city to the name
    assert matches_venue("The Regency Ballroom - San Francisco", "The Regency Ballroom", None)


def test_matches_venue_falls_back_to_city():
    assert matches_venue("Some Venue - San Francisco", "Different Name", "San Francisco")


def test_matches_venue_rejects_different_venue():
    assert not matches_venue("Madison Square Garden", "The Regency Ballroom", "San Francisco")


def test_matches_venue_handles_empty_inputs():
    assert not matches_venue("", "venue", "city")
    assert not matches_venue("some venue", None, None)
