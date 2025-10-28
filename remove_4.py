#!/usr/bin/env python3
"""
book_catalog.py

Single-file Book Catalog application with:
- HTML UI (Home, Books, Genres, Authors)
- REST API under /api/v1/
- CRUD for books, genres, authors
- Book search by publication date using yyyymmdd format
- Pagination, CSRF tokens, server-side validation
"""

import re
import os
from datetime import datetime, date
from functools import wraps
from math import ceil
from flask import (
    Flask, request, jsonify, render_template_string, redirect, url_for, flash,
    session, abort
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import secrets

# --------------------
# Configuration
# --------------------
APP_SECRET = os.environ.get("BOOK_CATALOG_SECRET") or secrets.token_hex(32)
DATABASE_PATH = os.environ.get("BOOK_CATALOG_DB") or "sqlite:///book_catalog.db"
PER_PAGE = 10  # number of books shown per page in HTML lists

app = Flask(__name__)
app.config["SECRET_KEY"] = APP_SECRET
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_PATH
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# --------------------
# Models
# --------------------
class Genre(db.Model):
    __tablename__ = "genres"
    Genre_ID = db.Column(db.Integer, primary_key=True)
    Genre_Name = db.Column(db.String(120), unique=True, nullable=False)
    Genre_Description = db.Column(db.String(500), nullable=True)

    def to_dict(self):
        return {
            "Genre_ID": self.Genre_ID,
            "Genre_Name": self.Genre_Name,
            "Genre_Description": self.Genre_Description or ""
        }

class Author(db.Model):
    __tablename__ = "authors"
    Author_ID = db.Column(db.Integer, primary_key=True)
    Author_Name = db.Column(db.String(120), unique=True, nullable=False)
    Author_Bio = db.Column(db.String(2000), nullable=True)

    def to_dict(self):
        return {
            "Author_ID": self.Author_ID,
            "Author_Name": self.Author_Name,
            "Author_Bio": self.Author_Bio or ""
        }

class Book(db.Model):
    __tablename__ = "books"
    Book_ID = db.Column(db.Integer, primary_key=True)
    Book_Title = db.Column(db.String(300), nullable=False)
    Book_Author = db.Column(db.String(120), nullable=False)  # store author name for simplicity
    Book_Genre = db.Column(db.String(120), nullable=False)   # store genre name for simplicity
    Book_Publication = db.Column(db.String(200), nullable=True)
    Book_Publication_Date = db.Column(db.Date, nullable=True)
    Book_Description = db.Column(db.String(2000), nullable=True)

    def to_dict(self):
        return {
            "Book_ID": self.Book_ID,
            "Book_Title": self.Book_Title,
            "Book_Author": self.Book_Author,
            "Book_Genre": self.Book_Genre,
            "Book_Publication": self.Book_Publication or "",
            "Book_Publication_Date": self.Book_Publication_Date.strftime("%Y-%m-%d") if self.Book_Publication_Date else "",
            "Book_Description": self.Book_Description or ""
        }

# --------------------
# Utilities
# --------------------

DATE_RE = re.compile(r"^\d{8}$")  # yyyymmdd

def parse_yyyymmdd(s):
    """Parse yyyymmdd into date object; returns None if invalid."""
    if not s:
        return None
    if not DATE_RE.match(s):
        return None
    try:
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except ValueError:
        return None

def make_csrf_token():
    token = secrets.token_urlsafe(32)
    session['_csrf_token'] = token
    return token

def validate_csrf():
    token_sess = session.get('_csrf_token')
    token_form = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
    return token_sess and token_form and secrets.compare_digest(token_sess, token_form)

def csrf_protect(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if request.method in ("POST", "PUT", "DELETE"):
            if not validate_csrf():
                return render_error("Invalid CSRF token", status=400)
        return f(*args, **kwargs)
    return wrapped

def render_error(message, status=400):
    # API errors should use JSON when request accepts application/json or is /api/
    if request.path.startswith("/api/") or request.accept_mimetypes.best == 'application/json':
        return jsonify({"message": message}), status
    # HTML fallback
    flash(message, "danger")
    return redirect(url_for("home"))

# JSON error formats required: single message: {"message": "Error message"}
# multiple messages: { "message" : { "error": ["message"], "error": ["message"] } }
def validation_errors_to_json(errors):
    # errors: dict field -> list of messages
    return {"message": {"error": [f"{k}: {', '.join(v)}" for k, v in errors.items()]}}

# --------------------
# Initialize DB (create tables)
# --------------------
@app.before_first_request
def create_tables():
    db.create_all()
    # create sample items only if empty
    if not Genre.query.first():
        g1 = Genre(Genre_Name="Fiction", Genre_Description="Fictional works")
        g2 = Genre(Genre_Name="Non-Fiction", Genre_Description="Non-fictional works")
        db.session.add_all([g1, g2])
    if not Author.query.first():
        a1 = Author(Author_Name="Jane Doe", Author_Bio="An example author.")
        a2 = Author(Author_Name="John Smith", Author_Bio="Another example author.")
        db.session.add_all([a1, a2])
    if not Book.query.first():
        b1 = Book(Book_Title="Sample Book 1", Book_Author="Jane Doe", Book_Genre="Fiction",
                  Book_Publication="Sample Publisher", Book_Publication_Date=date(2020,1,1),
                  Book_Description="A sample book.")
        db.session.add(b1)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()

# --------------------
# HTML Templates (inline for single-file)
# --------------------
BASE_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Book Catalog</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <!-- Bootstrap CDN for basic styling -->
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { padding-top: 4.5rem; }
    .container-main { max-width: 1100px; }
    .nav-fixed { position: fixed; top:0; left:0; right:0; z-index:1030; }
    .small-muted { font-size: .9rem; color: #666; }
    table td { vertical-align: middle; }
    form.inline { display: inline; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark nav-fixed">
  <div class="container">
    <a class="navbar-brand" href="{{ url_for('home') }}">Book Catalog</a>
    <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbars">
      <span class="navbar-toggler-icon"></span>
    </button>
    <div id="navbars" class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        <li class="nav-item"><a class="nav-link {% if active=='home' %}active{% endif %}" href="{{ url_for('home') }}">Home</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='books' %}active{% endif %}" href="{{ url_for('books') }}">Books</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='genres' %}active{% endif %}" href="{{ url_for('genres') }}">Genres</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='authors' %}active{% endif %}" href="{{ url_for('authors') }}">Authors</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='api' %}active{% endif %}" href="{{ url_for('api_info') }}">API</a></li>
      </ul>
    </div>
  </div>
</nav>

<main class="container container-main">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div>
        {% for cat, msg in messages %}
          <div class="alert alert-{{ 'success' if cat=='success' else 'danger' }}">{{ msg|e }}</div>
        {% endfor %}
      </div>
    {% endif %}
  {% endwith %}
  <div class="py-3">
    {% block content %}{% endblock %}
  </div>
</main>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

HOME_HTML = """
{% extends base %}
{% block content %}
  <div class="p-4 bg-light rounded">
    <h1>Welcome to the Book Catalog</h1>
    <p class="small-muted">Browse, create, update and delete Books, Genres, and Authors. Use the API under <code>/api/v1/</code>.</p>
    <hr>
    <div class="d-flex gap-2">
      <a class="btn btn-primary" href="{{ url_for('books') }}">Browse Books</a>
      <a class="btn btn-outline-secondary" href="{{ url_for('genres') }}">Genres</a>
      <a class="btn btn-outline-secondary" href="{{ url_for('authors') }}">Authors</a>
    </div>
  </div>
{% endblock %}
"""

API_INFO_HTML = """
{% extends base %}
{% block content %}
  <h2>API Info</h2>
  <p>Versioned API is available at <code>/api/v1/</code>. Responses use JSON.</p>
  <h4>Books</h4>
  <ul>
    <li>GET /api/v1/books - list books (supports <code>limit</code>, <code>offset</code>, <code>after_date</code>, <code>before_date</code>)</li>
    <li>GET /api/v1/books/&lt;book_id&gt;</li>
    <li>POST /api/v1/books</li>
    <li>PUT /api/v1/books/&lt;book_id&gt;</li>
    <li>DELETE /api/v1/books/&lt;book_id&gt;</li>
  </ul>
  <p><strong>Date format for queries:</strong> <code>yyyymmdd</code> (e.g. 20220131).</p>
{% endblock %}
"""

# Books list page with date range filter
BOOKS_HTML = """
{% extends base %}
{% block content %}
  <div class="d-flex justify-content-between align-items-center">
    <h2>Books</h2>
    <a class="btn btn-success" href="{{ url_for('book_create') }}">Create New</a>
  </div>

  <form method="get" class="row g-2 align-items-center my-3" action="{{ url_for('books') }}">
    <div class="col-auto">
      <label class="form-label">From (yyyymmdd)</label>
      <input name="after_date" class="form-control" value="{{ request.args.get('after_date','') }}" placeholder="yyyymmdd" aria-label="after_date">
    </div>
    <div class="col-auto">
      <label class="form-label">To (yyyymmdd)</label>
      <input name="before_date" class="form-control" value="{{ request.args.get('before_date','') }}" placeholder="yyyymmdd" aria-label="before_date">
    </div>
    <div class="col-auto align-self-end">
      <button class="btn btn-primary" type="submit" title="Filter">Refresh ↻</button>
    </div>
  </form>

  <div class="table-responsive">
    <table class="table table-striped table-hover">
      <thead><tr><th>ID</th><th>Title</th><th>Author</th><th>Genre</th><th>P_Date</th><th>Actions</th></tr></thead>
      <tbody>
        {% for b in books %}
          <tr>
            <td>{{ b.Book_ID }}</td>
            <td><a href="{{ url_for('book_detail', book_id=b.Book_ID) }}">{{ b.Book_Title|e }}</a></td>
            <td>{{ b.Book_Author|e }}</td>
            <td>{{ b.Book_Genre|e }}</td>
            <td>{{ b.Book_Publication_Date.strftime('%Y-%m-%d') if b.Book_Publication_Date else '' }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('book_update', book_id=b.Book_ID) }}">Update</a>
              <form method="post" action="{{ url_for('book_delete', book_id=b.Book_ID) }}" class="inline" onsubmit="return confirm('Confirm deletion?');">
                <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
                <button class="btn btn-sm btn-outline-danger" type="submit">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <!-- Pagination -->
  <nav aria-label="Page navigation">
    <ul class="pagination">
      {% if page>1 %}
        <li class="page-item"><a class="page-link" href="{{ url_for('books', page=page-1, after_date=request.args.get('after_date'), before_date=request.args.get('before_date')) }}">Previous</a></li>
      {% endif %}
      {% for p in pages %}
        <li class="page-item {% if p==page %}active{% endif %}"><a class="page-link" href="{{ url_for('books', page=p, after_date=request.args.get('after_date'), before_date=request.args.get('before_date')) }}">{{ p }}</a></li>
      {% endfor %}
      {% if page < total_pages %}
        <li class="page-item"><a class="page-link" href="{{ url_for('books', page=page+1, after_date=request.args.get('after_date'), before_date=request.args.get('before_date')) }}">Next</a></li>
      {% endif %}
    </ul>
  </nav>
{% endblock %}
"""

BOOK_DETAIL_HTML = """
{% extends base %}
{% block content %}
  <h2>Book details</h2>
  <table class="table">
    <tr><th>ID</th><td>{{ b.Book_ID }}</td></tr>
    <tr><th>Title</th><td>{{ b.Book_Title|e }}</td></tr>
    <tr><th>Author</th><td>{{ b.Book_Author|e }}</td></tr>
    <tr><th>Genre</th><td>{{ b.Book_Genre|e }}</td></tr>
    <tr><th>Description</th><td>{{ b.Book_Description|e }}</td></tr>
    <tr><th>Publication date</th><td>{{ b.Book_Publication_Date.strftime('%Y-%m-%d') if b.Book_Publication_Date else '' }}</td></tr>
  </table>
  <div class="d-flex gap-2">
    <a class="btn btn-primary" href="{{ url_for('book_update', book_id=b.Book_ID) }}">Update</a>
    <form method="post" action="{{ url_for('book_delete', book_id=b.Book_ID) }}" onsubmit="return confirm('Confirm deletion?');">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
      <button class="btn btn-danger" type="submit">Delete</button>
    </form>
    <a class="btn btn-secondary" href="{{ url_for('books') }}">Back to list</a>
  </div>
{% endblock %}
"""

BOOK_FORM_HTML = """
{% extends base %}
{% block content %}
  <h2>{{ 'Edit' if edit else 'Create New' }} Book</h2>
  <form method="post">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <div class="mb-3">
      <label class="form-label">Title *</label>
      <input class="form-control" name="Book_Title" value="{{ data.Book_Title|default('') }}" required maxlength="300">
    </div>
    <div class="mb-3">
      <label class="form-label">Author *</label>
      <select class="form-select" name="Book_Author" required>
        <option value="">-- choose author --</option>
        {% for a in authors %}
          <option value="{{ a.Author_Name|e }}" {% if data.Book_Author==a.Author_Name %}selected{% endif %}>{{ a.Author_Name|e }}</option>
        {% endfor %}
      </select>
      <div class="form-text">If author missing, create it in Authors page first.</div>
    </div>
    <div class="mb-3">
      <label class="form-label">Genre *</label>
      <select class="form-select" name="Book_Genre" required>
        <option value="">-- choose genre --</option>
        {% for g in genres %}
          <option value="{{ g.Genre_Name|e }}" {% if data.Book_Genre==g.Genre_Name %}selected{% endif %}>{{ g.Genre_Name|e }}</option>
        {% endfor %}
      </select>
      <div class="form-text">If genre missing, create it in Genres page first.</div>
    </div>
    <div class="mb-3">
      <label class="form-label">Publication (publisher)</label>
      <input class="form-control" name="Book_Publication" value="{{ data.Book_Publication|default('') }}" maxlength="200">
    </div>
    <div class="mb-3">
      <label class="form-label">Publication date (yyyy-mm-dd)</label>
      <input class="form-control" name="Book_Publication_Date" value="{{ data.Book_Publication_Date|default('') }}" placeholder="YYYY-MM-DD">
    </div>
    <div class="mb-3">
      <label class="form-label">Description</label>
      <textarea class="form-control" name="Book_Description" rows="4" maxlength="2000">{{ data.Book_Description|default('') }}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Submit</button>
    <a class="btn btn-secondary" href="{{ url_for('books') }}">Cancel</a>
  </form>
{% endblock %}
"""

# Genres & Authors templates (list, detail, create/update forms) - kept compact
GENRES_HTML = """
{% extends base %}
{% block content %}
  <div class="d-flex justify-content-between align-items-center">
    <h2>Genres</h2>
    <a class="btn btn-success" href="{{ url_for('genre_create') }}">Create new</a>
  </div>
  <div class="table-responsive my-3">
    <table class="table table-striped">
      <thead><tr><th>ID</th><th>Genre ID</th><th>Name</th><th>Description</th><th>Actions</th></tr></thead>
      <tbody>
        {% for g in genres %}
          <tr>
            <td>{{ loop.index + (page-1)*per_page }}</td>
            <td>{{ g.Genre_ID }}</td>
            <td><a href="{{ url_for('genre_detail', genre_id=g.Genre_ID) }}">{{ g.Genre_Name|e }}</a></td>
            <td>{{ g.Genre_Description|e }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('genre_update', genre_id=g.Genre_ID) }}">Update</a>
              <form method="post" action="{{ url_for('genre_delete', genre_id=g.Genre_ID) }}" class="inline" onsubmit="return confirm('Confirm deletion?');">
                <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
                <button class="btn btn-sm btn-outline-danger" type="submit">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <nav><ul class="pagination">
    {% if page>1 %}
      <li class="page-item"><a class="page-link" href="{{ url_for('genres', page=page-1) }}">Previous</a></li>
    {% endif %}
    {% for p in pages %}
      <li class="page-item {% if p==page %}active{% endif %}"><a class="page-link" href="{{ url_for('genres', page=p) }}">{{ p }}</a></li>
    {% endfor %}
    {% if page<total_pages %}
      <li class="page-item"><a class="page-link" href="{{ url_for('genres', page=page+1) }}">Next</a></li>
    {% endif %}
  </ul></nav>
{% endblock %}
"""

GENRE_DETAIL_HTML = """
{% extends base %}
{% block content %}
  <h2>Genre details</h2>
  <table class="table">
    <tr><th>Genre ID</th><td>{{ g.Genre_ID }}</td></tr>
    <tr><th>Name</th><td>{{ g.Genre_Name|e }}</td></tr>
    <tr><th>Description</th><td>{{ g.Genre_Description|e }}</td></tr>
  </table>
  <div class="d-flex gap-2">
    <a class="btn btn-primary" href="{{ url_for('genre_update', genre_id=g.Genre_ID) }}">Update</a>
    <form method="post" action="{{ url_for('genre_delete', genre_id=g.Genre_ID) }}" onsubmit="return confirm('Confirm deletion?');">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
      <button class="btn btn-danger" type="submit">Delete</button>
    </form>
    <a class="btn btn-secondary" href="{{ url_for('genres') }}">Back to list</a>
  </div>
{% endblock %}
"""

GENRE_FORM_HTML = """
{% extends base %}
{% block content %}
  <h2>{{ 'Edit' if edit else 'Create new' }} Genre</h2>
  <form method="post">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <div class="mb-3">
      <label class="form-label">Name *</label>
      <input class="form-control" name="Genre_Name" value="{{ data.Genre_Name|default('') }}" required maxlength="120">
    </div>
    <div class="mb-3">
      <label class="form-label">Description</label>
      <textarea class="form-control" name="Genre_Description" rows="4" maxlength="500">{{ data.Genre_Description|default('') }}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Submit</button>
    <a class="btn btn-secondary" href="{{ url_for('genres') }}">Cancel</a>
  </form>
{% endblock %}
"""

AUTHORS_HTML = """
{% extends base %}
{% block content %}
  <div class="d-flex justify-content-between align-items-center">
    <h2>Authors</h2>
    <a class="btn btn-success" href="{{ url_for('author_create') }}">Create new</a>
  </div>
  <div class="table-responsive my-3">
    <table class="table table-striped">
      <thead><tr><th>ID</th><th>Author ID</th><th>Name</th><th>Bio</th><th>Actions</th></tr></thead>
      <tbody>
        {% for a in authors %}
          <tr>
            <td>{{ loop.index + (page-1)*per_page }}</td>
            <td>{{ a.Author_ID }}</td>
            <td><a href="{{ url_for('author_detail', author_id=a.Author_ID) }}">{{ a.Author_Name|e }}</a></td>
            <td>{{ a.Author_Bio|e }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('author_update', author_id=a.Author_ID) }}">Update</a>
              <form method="post" action="{{ url_for('author_delete', author_id=a.Author_ID) }}" class="inline" onsubmit="return confirm('Confirm deletion?');">
                <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
                <button class="btn btn-sm btn-outline-danger" type="submit">Delete</button>
              </form>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <nav><ul class="pagination">
    {% if page>1 %}
      <li class="page-item"><a class="page-link" href="{{ url_for('authors', page=page-1) }}">Previous</a></li>
    {% endif %}
    {% for p in pages %}
      <li class="page-item {% if p==page %}active{% endif %}"><a class="page-link" href="{{ url_for('authors', page=p) }}">{{ p }}</a></li>
    {% endfor %}
    {% if page<total_pages %}
      <li class="page-item"><a class="page-link" href="{{ url_for('authors', page=page+1) }}">Next</a></li>
    {% endif %}
  </ul></nav>
{% endblock %}
"""

AUTHOR_DETAIL_HTML = """
{% extends base %}
{% block content %}
  <h2>Author details</h2>
  <table class="table">
    <tr><th>Author ID</th><td>{{ a.Author_ID }}</td></tr>
    <tr><th>Name</th><td>{{ a.Author_Name|e }}</td></tr>
    <tr><th>Bio</th><td>{{ a.Author_Bio|e }}</td></tr>
  </table>
  <div class="d-flex gap-2">
    <a class="btn btn-primary" href="{{ url_for('author_update', author_id=a.Author_ID) }}">Update</a>
    <form method="post" action="{{ url_for('author_delete', author_id=a.Author_ID) }}" onsubmit="return confirm('Confirm deletion?');">
      <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
      <button class="btn btn-danger" type="submit">Delete</button>
    </form>
    <a class="btn btn-secondary" href="{{ url_for('authors') }}">Back to list</a>
  </div>
{% endblock %}
"""

AUTHOR_FORM_HTML = """
{% extends base %}
{% block content %}
  <h2>{{ 'Edit' if edit else 'Create new' }} Author</h2>
  <form method="post">
    <input type="hidden" name="_csrf_token" value="{{ csrf_token }}">
    <div class="mb-3">
      <label class="form-label">Name *</label>
      <input class="form-control" name="Author_Name" value="{{ data.Author_Name|default('') }}" required maxlength="120">
    </div>
    <div class="mb-3">
      <label class="form-label">Bio</label>
      <textarea class="form-control" name="Author_Bio" rows="4" maxlength="2000">{{ data.Author_Bio|default('') }}</textarea>
    </div>
    <button class="btn btn-primary" type="submit">Submit</button>
    <a class="btn btn-secondary" href="{{ url_for('authors') }}">Cancel</a>
  </form>
{% endblock %}
"""

# --------------------
# HTML route handlers
# --------------------
def render_template_base(template_str, **context):
    # helper to provide base template and csrf_token
    ctx = dict(base=BASE_HTML, csrf_token=make_csrf_token())
    ctx.update(context)
    return render_template_string(template_str, **ctx)

@app.route("/")
def home():
    return render_template_base(HOME_HTML, active='home')

@app.route("/api-info")
def api_info():
    return render_template_base(API_INFO_HTML, active='api')

# --------------------
# Books: list, details, create, update, delete
# --------------------
@app.route("/books")
def books():
    # Pagination
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    after_date_raw = request.args.get("after_date")
    before_date_raw = request.args.get("before_date")
    after_date = parse_yyyymmdd(after_date_raw) if after_date_raw else None
    before_date = parse_yyyymmdd(before_date_raw) if before_date_raw else None

    q = Book.query
    if after_date:
        q = q.filter(Book.Book_Publication_Date >= after_date)
    if before_date:
        q = q.filter(Book.Book_Publication_Date <= before_date)

    total = q.count()
    total_pages = max(1, ceil(total / PER_PAGE))
    if page > total_pages:
        page = total_pages

    books = q.order_by(Book.Book_ID).offset((page-1)*PER_PAGE).limit(PER_PAGE).all()

    pages = list(range(1, total_pages+1))[:20]  # cap page links for UI simplicity
    return render_template_base(BOOKS_HTML, active='books', books=books, page=page,
                                pages=pages, total_pages=total_pages)

@app.route("/books/<int:book_id>")
def book_detail(book_id):
    b = Book.query.get_or_404(book_id)
    return render_template_base(BOOK_DETAIL_HTML, active='books', b=b)

@app.route("/books/create", methods=["GET", "POST"])
@csrf_protect
def book_create():
    if request.method == "GET":
        genres = Genre.query.order_by(Genre.Genre_Name).all()
        authors = Author.query.order_by(Author.Author_Name).all()
        return render_template_base(BOOK_FORM_HTML, active='books', edit=False, data={}, genres=genres, authors=authors)
    # POST: create
    data = {
        'Book_Title': request.form.get('Book_Title','').strip(),
        'Book_Author': request.form.get('Book_Author','').strip(),
        'Book_Genre': request.form.get('Book_Genre','').strip(),
        'Book_Publication': request.form.get('Book_Publication','').strip(),
        'Book_Publication_Date': request.form.get('Book_Publication_Date','').strip(),
        'Book_Description': request.form.get('Book_Description','').strip()
    }
    errors = {}
    if not data['Book_Title']:
        errors.setdefault('Book_Title', []).append('Title is required')
    if not data['Book_Author']:
        errors.setdefault('Book_Author', []).append('Author is required')
    if not data['Book_Genre']:
        errors.setdefault('Book_Genre', []).append('Genre is required')
    # Validate date format if provided (YYYY-MM-DD)
    pub_date = None
    if data['Book_Publication_Date']:
        try:
            pub_date = datetime.strptime(data['Book_Publication_Date'], "%Y-%m-%d").date()
        except ValueError:
            errors.setdefault('Book_Publication_Date', []).append('Invalid date format (expected YYYY-MM-DD)')
    if errors:
        genres = Genre.query.order_by(Genre.Genre_Name).all()
        authors = Author.query.order_by(Author.Author_Name).all()
        for k, v in errors.items():
            flash(f"{k}: {', '.join(v)}", "danger")
        return render_template_base(BOOK_FORM_HTML, active='books', edit=False, data=data, genres=genres, authors=authors)
    # persist
    book = Book(
        Book_Title=data['Book_Title'],
        Book_Author=data['Book_Author'],
        Book_Genre=data['Book_Genre'],
        Book_Publication=data['Book_Publication'],
        Book_Publication_Date=pub_date,
        Book_Description=data['Book_Description']
    )
    try:
        db.session.add(book)
        db.session.commit()
        flash("Book added successfully", "success")
        return redirect(url_for('books'))
    except Exception as e:
        db.session.rollback()
        return render_error("Error adding book: " + str(e))

@app.route("/books/<int:book_id>/update", methods=["GET", "POST"])
@csrf_protect
def book_update(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == "GET":
        data = book.to_dict()
        # convert date to YYYY-MM-DD for form
        data['Book_Publication_Date'] = book.Book_Publication_Date.strftime("%Y-%m-%d") if book.Book_Publication_Date else ""
        genres = Genre.query.order_by(Genre.Genre_Name).all()
        authors = Author.query.order_by(Author.Author_Name).all()
        return render_template_base(BOOK_FORM_HTML, active='books', edit=True, data=data, genres=genres, authors=authors)
    # POST update
    data = {
        'Book_Title': request.form.get('Book_Title','').strip(),
        'Book_Author': request.form.get('Book_Author','').strip(),
        'Book_Genre': request.form.get('Book_Genre','').strip(),
        'Book_Publication': request.form.get('Book_Publication','').strip(),
        'Book_Publication_Date': request.form.get('Book_Publication_Date','').strip(),
        'Book_Description': request.form.get('Book_Description','').strip()
    }
    errors = {}
    if not data['Book_Title']:
        errors.setdefault('Book_Title', []).append('Title is required')
    if not data['Book_Author']:
        errors.setdefault('Book_Author', []).append('Author is required')
    if not data['Book_Genre']:
        errors.setdefault('Book_Genre', []).append('Genre is required')
    pub_date = None
    if data['Book_Publication_Date']:
        try:
            pub_date = datetime.strptime(data['Book_Publication_Date'], "%Y-%m-%d").date()
        except ValueError:
            errors.setdefault('Book_Publication_Date', []).append('Invalid date format (expected YYYY-MM-DD)')
    if errors:
        genres = Genre.query.order_by(Genre.Genre_Name).all()
        authors = Author.query.order_by(Author.Author_Name).all()
        for k, v in errors.items():
            flash(f"{k}: {', '.join(v)}", "danger")
        return render_template_base(BOOK_FORM_HTML, active='books', edit=True, data=data, genres=genres, authors=authors)

    book.Book_Title = data['Book_Title']
    book.Book_Author = data['Book_Author']
    book.Book_Genre = data['Book_Genre']
    book.Book_Publication = data['Book_Publication']
    book.Book_Publication_Date = pub_date
    book.Book_Description = data['Book_Description']
    try:
        db.session.commit()
        flash("Book updated successfully", "success")
        return redirect(url_for('books'))
    except Exception as e:
        db.session.rollback()
        return render_error("Error updating book: " + str(e))

@app.route("/books/<int:book_id>/delete", methods=["POST"])
@csrf_protect
def book_delete(book_id):
    b = Book.query.get_or_404(book_id)
    try:
        db.session.delete(b)
        db.session.commit()
        # Per spec, successful deletion API returns {}
        flash("Book deleted", "success")
        return redirect(url_for('books'))
    except Exception as e:
        db.session.rollback()
        return render_error("Error deleting book: " + str(e))

# --------------------
# Genres routes
# --------------------
@app.route("/genres")
def genres():
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    per_page = 10
    q = Genre.query.order_by(Genre.Genre_ID)
    total = q.count()
    total_pages = max(1, ceil(total / per_page))
    if page > total_pages:
        page = total_pages
    genres = q.offset((page-1)*per_page).limit(per_page).all()
    pages = list(range(1, total_pages+1))[:20]
    return render_template_base(GENRES_HTML, active='genres', genres=genres, page=page, pages=pages, total_pages=total_pages, per_page=per_page)

@app.route("/genres/<int:genre_id>")
def genre_detail(genre_id):
    g = Genre.query.get_or_404(genre_id)
    return render_template_base(GENRE_DETAIL_HTML, active='genres', g=g)

@app.route("/genres/create", methods=["GET","POST"])
@csrf_protect
def genre_create():
    if request.method == "GET":
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=False, data={})
    name = request.form.get("Genre_Name","").strip()
    desc = request.form.get("Genre_Description","").strip()
    errors = {}
    if not name:
        errors.setdefault('Genre_Name', []).append('Name is required')
    if errors:
        for k, v in errors.items():
            flash(f"{k}: {', '.join(v)}", "danger")
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=False, data={'Genre_Name': name, 'Genre_Description': desc})
    g = Genre(Genre_Name=name, Genre_Description=desc)
    try:
        db.session.add(g)
        db.session.commit()
        flash("Genre created", "success")
        return redirect(url_for('genres'))
    except IntegrityError:
        db.session.rollback()
        flash("Genre with this name already exists", "danger")
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=False, data={'Genre_Name': name, 'Genre_Description': desc})
    except Exception as e:
        db.session.rollback()
        return render_error("Error creating genre: " + str(e))

@app.route("/genres/<int:genre_id>/update", methods=["GET","POST"])
@csrf_protect
def genre_update(genre_id):
    g = Genre.query.get_or_404(genre_id)
    if request.method == "GET":
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=True, data=g.to_dict())
    name = request.form.get("Genre_Name","").strip()
    desc = request.form.get("Genre_Description","").strip()
    if not name:
        flash("Name is required", "danger")
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=True, data={'Genre_Name': name, 'Genre_Description': desc})
    g.Genre_Name = name
    g.Genre_Description = desc
    try:
        db.session.commit()
        flash("Genre updated", "success")
        return redirect(url_for('genres'))
    except IntegrityError:
        db.session.rollback()
        flash("Genre with this name already exists", "danger")
        return render_template_base(GENRE_FORM_HTML, active='genres', edit=True, data={'Genre_Name': name, 'Genre_Description': desc})
    except Exception as e:
        db.session.rollback()
        return render_error("Error updating genre: " + str(e))

@app.route("/genres/<int:genre_id>/delete", methods=["POST"])
@csrf_protect
def genre_delete(genre_id):
    g = Genre.query.get_or_404(genre_id)
    try:
        db.session.delete(g)
        db.session.commit()
        flash("Genre deleted", "success")
        return redirect(url_for('genres'))
    except Exception as e:
        db.session.rollback()
        return render_error("Error deleting genre: " + str(e))

# --------------------
# Authors routes
# --------------------
@app.route("/authors")
def authors():
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    per_page = 10
    q = Author.query.order_by(Author.Author_ID)
    total = q.count()
    total_pages = max(1, ceil(total / per_page))
    if page > total_pages:
        page = total_pages
    authors = q.offset((page-1)*per_page).limit(per_page).all()
    pages = list(range(1, total_pages+1))[:20]
    return render_template_base(AUTHORS_HTML, active='authors', authors=authors, page=page, pages=pages, total_pages=total_pages, per_page=per_page)

@app.route("/authors/<int:author_id>")
def author_detail(author_id):
    a = Author.query.get_or_404(author_id)
    return render_template_base(AUTHOR_DETAIL_HTML, active='authors', a=a)

@app.route("/authors/create", methods=["GET","POST"])
@csrf_protect
def author_create():
    if request.method == "GET":
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=False, data={})
    name = request.form.get("Author_Name","").strip()
    bio = request.form.get("Author_Bio","").strip()
    if not name:
        flash("Name is required", "danger")
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=False, data={'Author_Name': name, 'Author_Bio': bio})
    a = Author(Author_Name=name, Author_Bio=bio)
    try:
        db.session.add(a)
        db.session.commit()
        flash("Author created", "success")
        return redirect(url_for('authors'))
    except IntegrityError:
        db.session.rollback()
        flash("Author with this name already exists", "danger")
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=False, data={'Author_Name': name, 'Author_Bio': bio})
    except Exception as e:
        db.session.rollback()
        return render_error("Error creating author: " + str(e))

@app.route("/authors/<int:author_id>/update", methods=["GET","POST"])
@csrf_protect
def author_update(author_id):
    a = Author.query.get_or_404(author_id)
    if request.method == "GET":
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=True, data=a.to_dict())
    name = request.form.get("Author_Name","").strip()
    bio = request.form.get("Author_Bio","").strip()
    if not name:
        flash("Name is required", "danger")
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=True, data={'Author_Name': name, 'Author_Bio': bio})
    a.Author_Name = name
    a.Author_Bio = bio
    try:
        db.session.commit()
        flash("Author updated", "success")
        return redirect(url_for('authors'))
    except IntegrityError:
        db.session.rollback()
        flash("Author with this name already exists", "danger")
        return render_template_base(AUTHOR_FORM_HTML, active='authors', edit=True, data={'Author_Name': name, 'Author_Bio': bio})
    except Exception as e:
        db.session.rollback()
        return render_error("Error updating author: " + str(e))

@app.route("/authors/<int:author_id>/delete", methods=["POST"])
@csrf_protect
def author_delete(author_id):
    a = Author.query.get_or_404(author_id)
    try:
        db.session.delete(a)
        db.session.commit()
        flash("Author deleted", "success")
        return redirect(url_for('authors'))
    except Exception as e:
        db.session.rollback()
        return render_error("Error deleting author: " + str(e))

# --------------------
# REST API endpoints (JSON)
# --------------------
# Helper: standardize error responses per spec
def api_error_single(msg, status=400):
    return jsonify({"message": msg}), status

def api_error_multiple(errors, status=400):
    # errors is dict field -> list messages
    return jsonify({"message": {"error": [f"{k}: {', '.join(v)}" for k, v in errors.items()]}}), status

@app.route("/api/v1/books", methods=["GET", "POST"])
def api_books():
    if request.method == "GET":
        # query args: limit, offset, before_date, after_date
        try:
            limit = int(request.args.get("limit", "10"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return api_error_single("limit and offset must be integers", 400)
        if limit < 0 or offset < 0:
            return api_error_single("limit and offset must be non-negative", 400)
        before_raw = request.args.get("before_date")
        after_raw = request.args.get("after_date")
        before_dt = parse_yyyymmdd(before_raw) if before_raw else None
        after_dt = parse_yyyymmdd(after_raw) if after_raw else None
        if (before_raw and not before_dt) or (after_raw and not after_dt):
            return api_error_single("Invalid date format. Use yyyymmdd", 400)
        q = Book.query
        if after_dt:
            q = q.filter(Book.Book_Publication_Date >= after_dt)
        if before_dt:
            q = q.filter(Book.Book_Publication_Date <= before_dt)
        items = q.order_by(Book.Book_ID).offset(offset).limit(limit).all()
        return jsonify([b.to_dict() for b in items])
    # POST create
    if not request.is_json:
        return api_error_single("Request body must be JSON", 400)
    payload = request.get_json()
    # required fields: Title, Author, Genre
    required = ["Book_Title", "Book_Author", "Book_Genre"]
    errors = {}
    for r in required:
        if not payload.get(r):
            errors.setdefault(r, []).append("Field is required")
    pub_date = None
    if payload.get("Book_Publication_Date"):
        # accept yyyymmdd or YYYY-MM-DD; try both
        s = str(payload.get("Book_Publication_Date"))
        dt = parse_yyyymmdd(s) or None
        if not dt:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d").date()
            except Exception:
                dt = None
        if dt is None:
            errors.setdefault("Book_Publication_Date", []).append("Invalid date (expected yyyymmdd or YYYY-MM-DD)")
        else:
            pub_date = dt
    if errors:
        return api_error_multiple(errors, 400)
    b = Book(
        Book_Title=str(payload.get("Book_Title")).strip()[:300],
        Book_Author=str(payload.get("Book_Author")).strip()[:120],
        Book_Genre=str(payload.get("Book_Genre")).strip()[:120],
        Book_Publication=str(payload.get("Book_Publication",""))[:200],
        Book_Publication_Date=pub_date,
        Book_Description=str(payload.get("Book_Description",""))[:2000]
    )
    try:
        db.session.add(b)
        db.session.commit()
        return jsonify(b.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return api_error_single("Error creating book: " + str(e), 500)

@app.route("/api/v1/books/<int:book_id>", methods=["GET", "PUT", "DELETE"])
def api_book_item(book_id):
    b = Book.query.get(book_id)
    if request.method == "GET":
        if not b:
            return api_error_single("Book not found", 404)
        return jsonify(b.to_dict())
    if request.method == "PUT":
        if not b:
            return api_error_single("Book not found", 404)
        if not request.is_json:
            return api_error_single("Request body must be JSON", 400)
        payload = request.get_json()
        # update allowed fields
        errors = {}
        if "Book_Title" in payload:
            if not payload.get("Book_Title"):
                errors.setdefault("Book_Title", []).append("Cannot be empty")
            else:
                b.Book_Title = str(payload.get("Book_Title"))[:300]
        if "Book_Author" in payload:
            if not payload.get("Book_Author"):
                errors.setdefault("Book_Author", []).append("Cannot be empty")
            else:
                b.Book_Author = str(payload.get("Book_Author"))[:120]
        if "Book_Genre" in payload:
            if not payload.get("Book_Genre"):
                errors.setdefault("Book_Genre", []).append("Cannot be empty")
            else:
                b.Book_Genre = str(payload.get("Book_Genre"))[:120]
        if "Book_Publication" in payload:
            b.Book_Publication = str(payload.get("Book_Publication",""))[:200]
        if "Book_Description" in payload:
            b.Book_Description = str(payload.get("Book_Description",""))[:2000]
        if "Book_Publication_Date" in payload:
            s = str(payload.get("Book_Publication_Date",""))
            dt = parse_yyyymmdd(s) or None
            if not dt:
                try:
                    dt = datetime.strptime(s, "%Y-%m-%d").date()
                except Exception:
                    dt = None
            if dt is None and s not in ("", None):
                errors.setdefault("Book_Publication_Date", []).append("Invalid date format")
            else:
                b.Book_Publication_Date = dt
        if errors:
            return api_error_multiple(errors, 400)
        try:
            db.session.commit()
            return jsonify(b.to_dict())
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error updating book: " + str(e), 500)
    # DELETE
    if request.method == "DELETE":
        if not b:
            return api_error_single("Book not found", 404)
        try:
            db.session.delete(b)
            db.session.commit()
            return jsonify({}), 204
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error deleting book: " + str(e), 500)

# --------------------
# Genres API
# --------------------
@app.route("/api/v1/genres", methods=["GET","POST"])
def api_genres():
    if request.method == "GET":
        try:
            limit = int(request.args.get("limit", "10"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return api_error_single("limit and offset must be integers", 400)
        items = Genre.query.order_by(Genre.Genre_ID).offset(offset).limit(limit).all()
        return jsonify([g.to_dict() for g in items])
    # POST create
    if not request.is_json:
        return api_error_single("Request must be JSON", 400)
    payload = request.get_json()
    name = payload.get("Genre_Name","").strip()
    desc = payload.get("Genre_Description","").strip() if payload.get("Genre_Description") else ""
    if not name:
        return api_error_single("Genre_Name is required", 400)
    g = Genre(Genre_Name=name[:120], Genre_Description=desc[:500])
    try:
        db.session.add(g)
        db.session.commit()
        return jsonify(g.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        return api_error_single("Genre with this name already exists", 409)
    except Exception as e:
        db.session.rollback()
        return api_error_single("Error creating genre: " + str(e), 500)

@app.route("/api/v1/genres/<int:genre_id>", methods=["GET","PUT","DELETE"])
def api_genre_item(genre_id):
    g = Genre.query.get(genre_id)
    if request.method == "GET":
        if not g:
            return api_error_single("Genre not found", 404)
        return jsonify(g.to_dict())
    if request.method == "PUT":
        if not g:
            return api_error_single("Genre not found", 404)
        if not request.is_json:
            return api_error_single("Request must be JSON", 400)
        payload = request.get_json()
        if "Genre_Name" in payload:
            if not payload.get("Genre_Name"):
                return api_error_single("Genre_Name cannot be empty", 400)
            g.Genre_Name = payload.get("Genre_Name")[:120]
        if "Genre_Description" in payload:
            g.Genre_Description = payload.get("Genre_Description","")[:500]
        try:
            db.session.commit()
            return jsonify(g.to_dict())
        except IntegrityError:
            db.session.rollback()
            return api_error_single("Genre with this name already exists", 409)
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error updating genre: " + str(e), 500)
    # DELETE
    if request.method == "DELETE":
        if not g:
            return api_error_single("Genre not found", 404)
        try:
            db.session.delete(g)
            db.session.commit()
            return jsonify({}), 204
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error deleting genre: " + str(e), 500)

# --------------------
# Authors API
# --------------------
@app.route("/api/v1/authors", methods=["GET","POST"])
def api_authors():
    if request.method == "GET":
        try:
            limit = int(request.args.get("limit", "10"))
            offset = int(request.args.get("offset", "0"))
        except ValueError:
            return api_error_single("limit and offset must be integers", 400)
        items = Author.query.order_by(Author.Author_ID).offset(offset).limit(limit).all()
        return jsonify([a.to_dict() for a in items])
    if not request.is_json:
        return api_error_single("Request must be JSON", 400)
    payload = request.get_json()
    name = payload.get("Author_Name","").strip()
    bio = payload.get("Author_Bio","").strip() if payload.get("Author_Bio") else ""
    if not name:
        return api_error_single("Author_Name is required", 400)
    a = Author(Author_Name=name[:120], Author_Bio=bio[:2000])
    try:
        db.session.add(a)
        db.session.commit()
        return jsonify(a.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        return api_error_single("Author with this name already exists", 409)
    except Exception as e:
        db.session.rollback()
        return api_error_single("Error creating author: " + str(e), 500)

@app.route("/api/v1/authors/<int:author_id>", methods=["GET","PUT","DELETE"])
def api_author_item(author_id):
    a = Author.query.get(author_id)
    if request.method == "GET":
        if not a:
            return api_error_single("Author not found", 404)
        return jsonify(a.to_dict())
    if request.method == "PUT":
        if not a:
            return api_error_single("Author not found", 404)
        if not request.is_json:
            return api_error_single("Request must be JSON", 400)
        payload = request.get_json()
        if "Author_Name" in payload:
            if not payload.get("Author_Name"):
                return api_error_single("Author_Name cannot be empty", 400)
            a.Author_Name = payload.get("Author_Name")[:120]
        if "Author_Bio" in payload:
            a.Author_Bio = payload.get("Author_Bio","")[:2000]
        try:
            db.session.commit()
            return jsonify(a.to_dict())
        except IntegrityError:
            db.session.rollback()
            return api_error_single("Author with this name already exists", 409)
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error updating author: " + str(e), 500)
    # DELETE
    if request.method == "DELETE":
        if not a:
            return api_error_single("Author not found", 404)
        try:
            db.session.delete(a)
            db.session.commit()
            return jsonify({}), 204
        except Exception as e:
            db.session.rollback()
            return api_error_single("Error deleting author: " + str(e), 500)

# --------------------
# Run app
# --------------------
if __name__ == "__main__":
    # For production, use gunicorn or uwsgi. This is for development / testing on Ubuntu.
    app.run(host="127.0.0.1", port=5000, debug=False)

