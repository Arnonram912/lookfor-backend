import unittest

from sqlalchemy import String

import models


class SqlServerSchemaTests(unittest.TestCase):
    def test_unique_string_columns_have_an_indexable_length(self):
        for table in models.Base.metadata.tables.values():
            for column in table.columns:
                if not column.unique or not isinstance(column.type, String):
                    continue
                self.assertIsNotNone(
                    column.type.length,
                    f"{table.name}.{column.name} must have a bounded length for SQL Server",
                )


if __name__ == "__main__":
    unittest.main()
