import unittest
from services.identity import canonicalize_whatsapp_number, hash_whatsapp_number


class TestIdentity(unittest.TestCase):
    def test_canonicalize_whatsapp_number(self):
        # International with plus
        self.assertEqual(canonicalize_whatsapp_number("+918698510857"), "918698510857")
        # International with spaces and hyphens
        self.assertEqual(canonicalize_whatsapp_number("+91 86985-10857"), "918698510857")
        # Raw digits already matching Meta format
        self.assertEqual(canonicalize_whatsapp_number("918698510857"), "918698510857")
        # 10-digit Indian national number starting with 8
        self.assertEqual(canonicalize_whatsapp_number("8698510857"), "918698510857")
        # Empty/None handling
        self.assertEqual(canonicalize_whatsapp_number(""), "")
        self.assertEqual(canonicalize_whatsapp_number(None), "")

    def test_hash_whatsapp_number(self):
        # All variations of the test phone number must yield the exact same SHA-256 hash
        expected_hash = "f428e3cebfbd9e2db6bd6d024b76441c753bab316b584fe013351d9a6acb0428"
        self.assertEqual(hash_whatsapp_number("918698510857"), expected_hash)
        self.assertEqual(hash_whatsapp_number("+918698510857"), expected_hash)
        self.assertEqual(hash_whatsapp_number("8698510857"), expected_hash)
        self.assertEqual(hash_whatsapp_number("+91 86985-10857"), expected_hash)


if __name__ == "__main__":
    unittest.main()
