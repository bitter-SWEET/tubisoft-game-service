import unittest

from ubisoft.rooms import RoomRegistry


def registration():
    return ["12", "1", ["launcher", "1", "Example", "XIIIPS2US", "6", "16", "0",
                         b"2?17?20?10?N?8:7777", b"\0", "", "1.0", "XIIIPS21.0",
                         "8208", "192.0.2.2", "7777", b""]]


class RoomRegistryTests(unittest.TestCase):
    def test_remove_event_requires_owner_and_occurs_once(self):
        registry = RoomRegistry()
        room = registry.register("user", "192.0.2.2", registration())
        removed = []
        registry.add_remove_listener(removed.append)
        registry.remove(room.room_id, "other", room.peer_ip)
        self.assertEqual(removed, [])
        registry.remove(room.room_id, room.owner, room.peer_ip)
        registry.remove(room.room_id, room.owner, room.peer_ip)
        self.assertEqual(removed, [room])
        registry.remove_remove_listener(removed.append)
        next_room = registry.register("user", "192.0.2.2", registration())
        registry.remove(next_room.room_id, next_room.owner, next_room.peer_ip)
        self.assertEqual(removed, [room])

    def test_room_requires_owner_activation_and_disappears_on_remove(self):
        registry = RoomRegistry()
        room = registry.register("user", "192.0.2.2", registration())
        self.assertEqual(registry.children(), [])
        self.assertIsNone(registry.activate(room.room_id, "other", "192.0.2.2"))
        self.assertIsNone(registry.activate(room.room_id, "user", "192.0.2.3"))
        self.assertIs(registry.activate(room.room_id, "user", "192.0.2.2"), room)
        self.assertEqual(registry.children()[0][2], str(room.room_id))
        self.assertEqual(registry.children()[0][10], b"2?17?20?10?N?8:7777")
        registry.remove(room.room_id, "other", "192.0.2.2")
        self.assertEqual(len(registry.children()), 1)
        registry.remove(room.room_id, "user", "192.0.2.2")
        self.assertEqual(registry.children(), [])

    def test_rejects_unsupported_or_duplicate_requests(self):
        registry = RoomRegistry()
        malformed = registration()
        malformed[2][7] = "not binary"
        with self.assertRaises(ValueError):
            registry.register("user", "192.0.2.2", malformed)
        private = registration()
        private[2][9] = "secret"
        with self.assertRaises(ValueError):
            registry.register("user", "192.0.2.2", private)
        registry.register("user", "192.0.2.2", registration())
        with self.assertRaises(ValueError):
            registry.register("user", "192.0.2.2", registration())

    def test_pending_room_survives_launcher_close_but_eventually_expires(self):
        registry = RoomRegistry()
        room = registry.register("user", "192.0.2.2", registration())
        registry.expire_pending(room.pending_until - 1)
        self.assertIs(registry.activate(room.room_id, "user", "192.0.2.2"), room)
        registry.expire_pending(room.pending_until + 1)
        self.assertEqual(len(registry.children()), 1)

        abandoned = registry.register("other", "192.0.2.3", registration())
        registry.expire_pending(abandoned.pending_until)
        self.assertIsNone(registry.activate(abandoned.room_id, "other", "192.0.2.3"))
        registry.register("other", "192.0.2.3", registration())


if __name__ == "__main__":
    unittest.main()
