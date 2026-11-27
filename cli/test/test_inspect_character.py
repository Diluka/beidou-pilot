import unittest
from unittest.mock import Mock

from beidou_pilot.cli import dispatch, parser
from beidou_pilot.errors import ClientError


class InspectCharacterTest(unittest.TestCase):
    def test_both_backends_return_native_observation_unchanged(self):
        for name in ("beidou",):
            for character, valid in (({"id": 1, "strength": 10, "dexterity": 4,
                                      "intelligence": 4, "luck": 4, "ability_points": 2}, True),
                                     (None, False)):
                with self.subTest(backend=name, valid=valid):
                    backend = Mock()
                    backend.name = name
                    observed = {"character": character, "native_values_valid": valid,
                                "unavailable": [] if valid else ["not ready"], "seq": 42}
                    backend.read.return_value = observed
                    result = dispatch(backend, parser().parse_args(["inspect", "character"]))
                    self.assertIs(result, observed)
                    backend.read.assert_called_once_with("observe")

    def test_observation_errors_propagate(self):
        for name in ("beidou",):
            with self.subTest(backend=name):
                backend = Mock()
                backend.name = name
                error = ClientError("native_observation_not_ready", "not ready")
                backend.read.side_effect = error
                with self.assertRaises(ClientError) as caught:
                    dispatch(backend, parser().parse_args(["inspect", "character"]))
                self.assertIs(caught.exception, error)

    def test_skills_keeps_character_domain(self):
        for name in ("beidou",):
            with self.subTest(backend=name):
                backend = Mock()
                backend.name = name
                dispatch(backend, parser().parse_args(["inspect", "skills"]))
                backend.read.assert_called_once_with("character")

    def test_character_rejects_identifier(self):
        backend = Mock()
        backend.name = "beidou"
        with self.assertRaises(ClientError) as caught:
            dispatch(backend, parser().parse_args(["inspect", "character", "123"]))
        self.assertEqual(caught.exception.code, "usage")
        backend.read.assert_not_called()
