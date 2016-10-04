# -*- coding: utf-8 -*-

import uuid


def generate_peer_id():
    """Generate random 20-byte string to uniquely identify the peer.

    The protocol doesn't specify any algorithm to follow.
    There is a guidelines in As per https://wiki.theory.org/BitTorrentSpecification,
    but I will stick with first 20 characters of UUID.
    """
    return bytes(str(uuid.uuid4())[:20].encode('utf-8'))
