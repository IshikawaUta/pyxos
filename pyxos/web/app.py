from fenrir import Fenrir, render_template, request, redirect
from fenrir.static import StaticFiles
from pathlib import Path

BASE_DIR = Path(__file__).parent


def _render(template_name, **context):
    return render_template(template_name, request=request, **context)


def mask_value(value, show=6):
    if not value:
        return "(not set)"
    s = str(value)
    if len(s) <= show + 4:
        return s[:4] + "***" if len(s) > 4 else s
    return s[:show] + "***"


def format_size(size):
    if size is None or size < 0:
        return "-"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / 1024:.1f} KB"


def get_data():
    from pyxos.config import load_config
    from pyxos.database import Database

    cfg = load_config()
    uri = cfg.get("mongodb_uri")
    if not uri:
        return None, None, None

    db = Database(uri)
    try:
        projects, total = db.list_projects(per_page=100)
        stats = {
            "total_projects": total,
            "total_size": sum(p.get("file_size", 0) for p in projects),
            "storage_backends": len(set(p.get("storage_type", "cloudinary") for p in projects)),
        }
        return db, projects, stats
    except Exception:
        return db, [], {"total_projects": 0, "total_size": 0, "storage_backends": 0}


def create_app():
    app = Fenrir(
        title="Pyxos Dashboard",
        version="1.0.0",
        template_folder=str(BASE_DIR / "templates"),
    )

    static_dir = BASE_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)))

    from pyxos.config import load_config

    @app.route("/")
    def index():
        db, projects, stats = get_data()
        if db is None:
            return _render("error.html", message="Pyxos not configured. Run 'pyxos init' first.")
        recent = sorted(projects, key=lambda p: p.get("updated_at") or 0, reverse=True)[:10]
        db.close()
        return _render("index.html", stats=stats, recent=recent, format_size=format_size)

    @app.route("/projects")
    def projects_list():
        db, _, _ = get_data()
        if db is None:
            return _render("error.html", message="Pyxos not configured.")

        search = request.args.get("search", "").strip()
        page = int(request.args.get("page", "1"))
        per_page = 20

        projects, total = db.list_projects(search=search if search else None, page=page, per_page=per_page)
        total_pages = max(1, (total + per_page - 1) // per_page)
        db.close()

        return _render(
            "projects.html",
            projects=projects,
            total=total,
            page=page,
            total_pages=total_pages,
            search=search,
            format_size=format_size,
        )

    @app.route("/projects/<id>")
    def project_detail(id):
        db, _, _ = get_data()
        if db is None:
            return _render("error.html", message="Pyxos not configured.")

        project = db.get_project(project_id=id)
        if not project:
            db.close()
            return _render("error.html", message="Project not found."), 404

        db.close()
        return _render("project_detail.html", project=project, format_size=format_size)

    @app.route("/projects/delete/<id>", methods=["POST"])
    def delete_project_route(id):
        db, _, _ = get_data()
        if db is None:
            return redirect("/")

        cfg = load_config()
        project = db.get_project(project_id=id)
        if not project:
            db.close()
            return redirect("/projects")

        public_id = project.get("storage_public_id") or project.get("cloudinary_public_id")
        if public_id:
            try:
                from pyxos.storage import delete_project as cloud_delete, init_storage
                init_storage(cfg)
                cloud_delete(public_id)
            except Exception:
                pass

        db.delete_project(project_id=project["_id"])
        db.close()
        return redirect("/projects")

    @app.route("/config")
    def config_view():
        cfg = load_config()
        st = cfg.get("storage_type", "cloudinary")
        return _render("config.html", cfg=cfg, st=st, mask_value=mask_value)

    @app.route("/stats")
    def stats():
        db, projects, stats = get_data()
        if db is None:
            return _render("error.html", message="Pyxos not configured.")

        storage_types = {}
        for p in projects:
            st = p.get("storage_type", "cloudinary")
            storage_types[st] = storage_types.get(st, 0) + 1

        size_dist = {}
        for p in projects:
            sz = p.get("file_size", 0)
            if sz < 1024 * 1024:
                bucket = "< 1 MB"
            elif sz < 10 * 1024 * 1024:
                bucket = "1-10 MB"
            elif sz < 50 * 1024 * 1024:
                bucket = "10-50 MB"
            elif sz < 100 * 1024 * 1024:
                bucket = "50-100 MB"
            else:
                bucket = "> 100 MB"
            size_dist[bucket] = size_dist.get(bucket, 0) + 1

        version_counts = {}
        for p in projects:
            v = p.get("version", "unknown")
            version_counts[v] = version_counts.get(v, 0) + 1

        total_tags = len(set(tag for p in projects for tag in p.get("tags", [])))

        db.close()
        return _render(
            "stats.html",
            stats=stats,
            storage_types=storage_types,
            size_dist=size_dist,
            version_counts=version_counts,
            total_tags=total_tags,
            format_size=format_size,
        )

    return app


app = create_app()
