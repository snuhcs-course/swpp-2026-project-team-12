def family_group(family_id):
    assert type(family_id) is int and family_id > 0
    return f"family_{family_id}"
