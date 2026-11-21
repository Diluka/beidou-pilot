import unittest

from beidou_pilot.errors import ClientError
from beidou_pilot.validation import Integer, ListField, Object, String, validate


class ValidationTest(unittest.TestCase):
    def test_reports_field_and_reason(self):
        schema = Object({"name": String(), "count": Integer(minimum=1)})
        with self.assertRaises(ClientError) as error:
            validate({"name": "", "count": 0}, schema, code="input_invalid", label="参数")
        self.assertEqual("input_invalid", error.exception.code)
        self.assertEqual("name", error.exception.details["field"])
        self.assertIn("不能为空", error.exception.message)

    def test_applies_defaults_and_rejects_extra_fields(self):
        schema = Object({"name": String(), "count": Integer(default=1)})
        self.assertEqual({"name": "x", "count": 1}, validate({"name": "x"}, schema, code="input_invalid", label="参数"))
        with self.assertRaises(ClientError) as error:
            validate({"name": "x", "other": 2}, schema, code="input_invalid", label="参数")
        self.assertIn("未知字段", error.exception.message)

    def test_reports_list_item_path(self):
        schema = Object({"items": ListField(Integer(), maximum=2)})
        with self.assertRaises(ClientError) as error:
            validate({"items": [1, "x"]}, schema, code="input_invalid", label="参数")
        self.assertEqual("items[1]", error.exception.details["field"])
