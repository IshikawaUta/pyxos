import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import MongoClient
from pymongo import errors as mongo_errors

COLLECTION_NAME = "projects"
VERSIONS_COLLECTION = "pyxos.versions"


def _to_objectid(maybe_id):
    if isinstance(maybe_id, ObjectId):
        return maybe_id
    if maybe_id is None:
        return None
    try:
        return ObjectId(maybe_id)
    except InvalidId:
        return None


class Database:
    def __init__(self, uri):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        self.db = self.client.pyxos
        self.collection = self.db[COLLECTION_NAME]
        self.versions = self.db[VERSIONS_COLLECTION]

    def check_connection(self):
        try:
            self.client.admin.command("ping")
            return True
        except mongo_errors.ServerSelectionTimeoutError:
            return False
        except mongo_errors.PyMongoError:
            return False

    def create_project(self, name, description, tags, storage_url, storage_public_id, local_path, file_size=0, file_count=0, version="1.0.0", storage_type="cloudinary", encrypted=False):
        doc = {
            "name": name,
            "description": description,
            "tags": tags or [],
            "storage_url": storage_url,
            "storage_public_id": storage_public_id,
            "local_path": local_path,
            "file_size": file_size,
            "file_count": file_count,
            "version": version,
            "storage_type": storage_type,
            "encrypted": encrypted,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        result = self.collection.insert_one(doc)
        return str(result.inserted_id)

    def update_project(self, project_id, **kwargs):
        oid = _to_objectid(project_id)
        if oid is None:
            return 0
        kwargs["updated_at"] = datetime.now(timezone.utc)
        r = self.collection.update_one({"_id": oid}, {"$set": kwargs})
        return r.modified_count

    def get_project(self, project_id=None, name=None):
        if project_id:
            oid = _to_objectid(project_id)
            if oid:
                return self.collection.find_one({"_id": oid})
        if name:
            return self.collection.find_one({"name": name})
        return None

    def list_projects(self, search=None, tags=None, page=1, per_page=20):
        query = {}
        if search:
            escaped = re.escape(search)
            query["$or"] = [
                {"name": {"$regex": escaped, "$options": "i"}},
                {"description": {"$regex": escaped, "$options": "i"}},
            ]
        if tags:
            query["tags"] = {"$all": tags} if isinstance(tags, list) else {"$in": [tags]}

        total = self.collection.count_documents(query)
        skip = (page - 1) * per_page
        cursor = self.collection.find(query).sort("updated_at", -1).skip(skip).limit(per_page)
        projects = list(cursor)
        return projects, total

    def delete_project(self, project_id=None, name=None):
        if project_id:
            oid = _to_objectid(project_id)
            if oid:
                return self.collection.delete_one({"_id": oid}).deleted_count
        if name:
            return self.collection.delete_one({"name": name}).deleted_count
        return 0

    def save_version(self, project):
        doc = {
            "project_id": str(project["_id"]),
            "version": project.get("version", "1.0.0"),
            "storage_public_id": project.get("storage_public_id") or project.get("cloudinary_public_id"),
            "storage_url": project.get("storage_url") or project.get("cloudinary_url"),
            "file_size": project.get("file_size", 0),
            "file_count": project.get("file_count", 0),
            "created_at": datetime.now(timezone.utc),
        }
        result = self.versions.insert_one(doc)
        return str(result.inserted_id)

    def get_versions(self, project_id):
        return list(self.versions.find(
            {"project_id": str(project_id)}
        ).sort("created_at", -1))

    def get_version(self, version_id):
        try:
            return self.versions.find_one({"_id": ObjectId(version_id)})
        except InvalidId:
            return None

    def delete_versions(self, project_id):
        return self.versions.delete_many({"project_id": str(project_id)}).deleted_count

    def close(self):
        self.client.close()
