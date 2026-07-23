from unittest.mock import MagicMock

import pytest
from bson import ObjectId
from pymongo import errors as mongo_errors

from pyxos.database import _to_objectid


class TestToObjectId:
    def test_with_objectid(self):
        oid = ObjectId()
        assert _to_objectid(oid) == oid

    def test_with_valid_string(self):
        oid = ObjectId()
        assert _to_objectid(str(oid)) == oid

    def test_with_invalid_string(self):
        assert _to_objectid("not_an_id") is None

    def test_with_none(self):
        assert _to_objectid(None) is None


class TestDatabase:
    def test_init(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        assert db.client is client
        assert db.collection is coll

    def test_check_connection_success(self, mock_mongo_client):
        db, client, _ = mock_mongo_client
        assert db.check_connection() is True

    def test_check_connection_timeout(self, mock_mongo_client):
        db, client, _ = mock_mongo_client
        client.admin.command.side_effect = mongo_errors.ServerSelectionTimeoutError("timeout")
        assert db.check_connection() is False

    def test_check_connection_other_error(self, mock_mongo_client):
        db, client, _ = mock_mongo_client
        client.admin.command.side_effect = mongo_errors.PyMongoError("boom")
        assert db.check_connection() is False

    def test_create_project(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        oid = ObjectId()
        coll.insert_one.return_value.inserted_id = oid

        result = db.create_project(
            name="testproj", description="desc", tags=["py"],
            storage_url="https://c.com/z.zip", storage_public_id="pyxos/t",
            local_path="/tmp", file_size=1024, file_count=5, version="2.0.0",
        )
        assert result == str(oid)
        doc = coll.insert_one.call_args[0][0]
        assert doc["version"] == "2.0.0"

    def test_create_project_minimal(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        oid = ObjectId()
        coll.insert_one.return_value.inserted_id = oid

        result = db.create_project(
            name="min", description="", tags=None,
            storage_url="https://x.com/z.zip", storage_public_id="pyxos/m",
            local_path="/tmp",
        )
        assert result == str(oid)

    def test_update_project(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        oid = ObjectId()
        coll.update_one.return_value.modified_count = 1

        assert db.update_project(str(oid), desc="new") == 1
        coll.update_one.assert_called_once()

    def test_update_project_invalid_id(self, mock_mongo_client):
        db, _, _ = mock_mongo_client
        assert db.update_project("bad", x="y") == 0

    def test_get_project_by_id(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        oid = ObjectId()
        expected = {"_id": oid, "name": "p"}
        coll.find_one.return_value = expected
        assert db.get_project(project_id=str(oid)) == expected

    def test_get_project_by_name(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        expected = {"_id": ObjectId(), "name": "p"}
        coll.find_one.return_value = expected
        assert db.get_project(name="p") == expected

    def test_get_project_invalid_id(self, mock_mongo_client):
        db, _, _ = mock_mongo_client
        assert db.get_project(project_id="bad") is None

    def test_get_project_no_args(self, mock_mongo_client):
        db, _, _ = mock_mongo_client
        assert db.get_project() is None

    def test_list_projects_basic(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        p1 = {"_id": ObjectId(), "name": "p1"}
        p2 = {"_id": ObjectId(), "name": "p2"}
        coll.count_documents.return_value = 2
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = [p1, p2]
        coll.find.return_value = cursor
        projs, total = db.list_projects()
        assert total == 2
        assert len(projs) == 2

    def test_list_projects_with_search(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        coll.count_documents.return_value = 1
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = [{"_id": ObjectId(), "name": "api"}]
        coll.find.return_value = cursor
        _, total = db.list_projects(search="api")
        assert total == 1

    def test_list_projects_with_tags_list(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        coll.count_documents.return_value = 0
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = []
        coll.find.return_value = cursor
        db.list_projects(tags=["py", "web"])
        query = coll.find.call_args[0][0]
        assert query["tags"] == {"$all": ["py", "web"]}

    def test_list_projects_with_single_tag(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        coll.count_documents.return_value = 0
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = []
        coll.find.return_value = cursor
        db.list_projects(tags="py")
        query = coll.find.call_args[0][0]
        assert query["tags"] == {"$in": ["py"]}

    def test_list_projects_pagination(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        coll.count_documents.return_value = 50
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = []
        coll.find.return_value = cursor
        db.list_projects(page=3, per_page=10)
        cursor.skip.assert_called_with(20)
        cursor.limit.assert_called_with(10)

    def test_delete_project_by_id(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        oid = ObjectId()
        coll.delete_one.return_value.deleted_count = 1
        assert db.delete_project(project_id=str(oid)) == 1

    def test_delete_project_by_name(self, mock_mongo_client):
        db, client, coll = mock_mongo_client
        coll.delete_one.return_value.deleted_count = 1
        assert db.delete_project(name="p") == 1

    def test_delete_project_invalid_id(self, mock_mongo_client):
        db, _, _ = mock_mongo_client
        assert db.delete_project(project_id="bad") == 0

    def test_delete_project_no_args(self, mock_mongo_client):
        db, _, _ = mock_mongo_client
        assert db.delete_project() == 0

    def test_close(self, mock_mongo_client):
        db, client, _ = mock_mongo_client
        db.close()
        client.close.assert_called_once()
