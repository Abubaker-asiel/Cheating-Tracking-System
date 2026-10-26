import numpy as np

from invigil.features import (Person, Phone, head_yaw_proxy, neighbor_in_direction,
                              phone_owner, wrist_owner)


def kp(**pts):
    k = np.zeros((17, 3))
    idx = dict(nose=0, le=1, re=2, lear=3, rear=4, ls=5, rs=6, lw=9, rw=10)
    for name, (x, y) in pts.items():
        k[idx[name]] = (x, y, 0.9)
    return k


def person(tid, x1, kpts=None, w=100, y1=0, h=200):
    return Person(tid, (x1, y1, x1 + w, y1 + h), kpts)


def test_yaw_sign_follows_image_direction():
    right = person(1, 0, kp(nose=(70, 40), le=(40, 30), re=(60, 30), ls=(20, 100), rs=(80, 100)))
    left = person(1, 0, kp(nose=(30, 40), le=(40, 30), re=(60, 30), ls=(20, 100), rs=(80, 100)))
    front = person(1, 0, kp(nose=(50, 40), le=(40, 30), re=(60, 30), ls=(20, 100), rs=(80, 100)))
    assert head_yaw_proxy(right, 0.35)[0] > 0.2
    assert head_yaw_proxy(left, 0.35)[0] < -0.2
    assert abs(head_yaw_proxy(front, 0.35)[0]) < 0.01


def test_yaw_none_without_face_points():
    assert head_yaw_proxy(person(1, 0, None), 0.35) is None
    assert head_yaw_proxy(person(1, 0, kp(nose=(50, 40))), 0.35) is None


def test_neighbor_must_be_on_the_turned_side_and_close():
    a, b, far = person(1, 0), person(2, 120), person(3, 900)
    assert neighbor_in_direction(a, [a, b, far], +1, 2.5).track_id == 2
    assert neighbor_in_direction(a, [a, b, far], -1, 2.5) is None
    assert neighbor_in_direction(a, [a, far], +1, 2.5) is None


def test_neighbor_in_other_row_is_ignored():
    a, other_row = person(1, 0), person(2, 120, y1=400)
    assert neighbor_in_direction(a, [a, other_row], +1, 2.5) is None


def test_phone_needs_wrist_proximity_when_hands_are_visible():
    holder = person(1, 0, kp(ls=(20, 100), rs=(80, 100), rw=(50, 150)))
    other = person(2, 120, kp(ls=(140, 100), rs=(200, 100), lw=(180, 400)))
    near = Phone((45, 140, 60, 160), 0.8)
    assert phone_owner(near, [holder, other], 0.35, 0.8) == 1
    desk = Phone((10, 10, 25, 25), 0.8)  # inside the box but nowhere near a wrist
    assert phone_owner(desk, [holder, other], 0.35, 0.8) is None
    assert phone_owner(desk, [holder, other], 0.35, 0.8, require_wrist=False) == 1


def test_phone_falls_back_to_box_when_no_hands_visible():
    p = person(1, 0, kp(ls=(20, 100), rs=(80, 100)))
    assert phone_owner(Phone((40, 100, 60, 120), 0.7), [p], 0.35, 0.8) == 1


def test_wrist_belongs_to_nearest_body():
    a, b = person(1, 0), person(2, 90)  # boxes overlap on x in 90..100
    assert wrist_owner(95, 100, [a, b]) == 2 or wrist_owner(95, 100, [a, b]) == 1
    assert wrist_owner(140, 100, [a, b]) == 2
    assert wrist_owner(500, 100, [a, b]) is None
