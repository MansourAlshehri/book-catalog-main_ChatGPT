#!/usr/bin/env python3
"""
book_catalog.py — Single-file Book Catalog web app (Flask + SQLite)

Features:
- HTML UI and REST API for Books, Genres, Authors
- CRUD operations, pagination, date-range search (yyyymmdd)
- CSRF protection, server-side validation, safe DB usage via SQLAlchemy
- Security headers via Flask-Talisman

Dependencies:
  pip install Flask Flask-WTF Flask-SQLAlchemy python-dateutil Flask-Talisman

Run:
  python book_catalog.py
  then open http://127.0.0.1:5000/

Author: Generated code (adapt as needed)
"""

from flask import (
    Flask, render_template_string, request, redirect, url_for,
    flash, jsonify, abort
)
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, TextAreaField, DateField, SelectField, IntegerField
from wtforms.validators import DataRequired, Length, Optional
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, and_
from datetime import datetime
from dateutil import parser as date_parser
import os
from flask_talisman import Talisman

# --- Configuration ---
APP_SECRET = os.environ.get("BOOKCAT_SECRET") or "change-me-to-a-secure-random-value"
DATABASE = os.environ.get("BOOKCAT_DB") or "sqlite:///catalog.db"
PAGE_SIZE = 10  # number of books per page in HTML list

app = Flask(__name__)
app.config['SECRET_KEY'] = APP_SECRET
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Security headers (Talisman) — basic; adjust CSP if adding external resources
Talisman(app, content_security_policy={
    'default-src': ["'self'"],
    'script-src': ["'self'", "https://cdn.jsdelivr.net", "https://code.jquery.com", "'unsafe-inline'"],
    'style-src': ["'self'", "https://cdn.jsdelivr.net", "https://stackpath.bootstrapcdn.com", "'unsafe-inline'"],
    'img-src': ["'self'", "data:"]
})

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# --- Models ---
class Genre(db.Model):
    __tablename__ = 'genres'
    Genre_ID = db.Column(db.Integer, primary_key=True)
    Genre_Name = db.Column(db.String(120), nullable=False, unique=True)
    Genre_Description = db.Column(db.String(1000), nullable=True)

    def to_dict(self):
        return {
            "Genre_ID": self.Genre_ID,
            "Genre_Name": self.Genre_Name,
            "Genre_Description": self.Genre_Description or ""
        }


class Author(db.Model):
    __tablename__ = 'authors'
    Author_ID = db.Column(db.Integer, primary_key=True)
    Author_Name = db.Column(db.String(200), nullable=False, unique=True)
    Author_Bio = db.Column(db.String(2000), nullable=True)

    def to_dict(self):
        return {
            "Author_ID": self.Author_ID,
            "Author_Name": self.Author_Name,
            "Author_Bio": self.Author_Bio or ""
        }


class Book(db.Model):
    __tablename__ = 'books'
    Book_ID = db.Column(db.Integer, primary_key=True)
    Book_Title = db.Column(db.String(300), nullable=False)
    Book_Author = db.Column(db.String(200), nullable=False)
    Book_Genre = db.Column(db.String(120), nullable=False)
    Book_Publication = db.Column(db.String(200), nullable=True)
    Book_Publication_Date = db.Column(db.Date, nullable=True)
    Book_Description = db.Column(db.String(5000), nullable=True)

    def to_dict(self):
        return {
            "Book_ID": self.Book_ID,
            "Book_Title": self.Book_Title,
            "Book_Author": self.Book_Author,
            "Book_Genre": self.Book_Genre,
            "Book_Publication": self.Book_Publication or "",
            "Book_Publication_Date": self.Book_Publication_Date.isoformat() if self.Book_Publication_Date else None,
            "Book_Description": self.Book_Description or ""
        }


# --- Forms ---
class BookForm(FlaskForm):
    Book_Title = StringField("Title", validators=[DataRequired(), Length(max=300)])
    Book_Author = StringField("Author", validators=[DataRequired(), Length(max=200)])
    Book_Genre = StringField("Genre", validators=[DataRequired(), Length(max=120)])
    Book_Publication = StringField("Publication", validators=[Optional(), Length(max=200)])
    Book_Publication_Date = StringField("Publication date (YYYY-MM-DD)", validators=[Optional(), Length(max=10)])
    Book_Description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])


class GenreForm(FlaskForm):
    Genre_Name = StringField("Name", validators=[DataRequired(), Length(max=120)])
    Genre_Description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])


class AuthorForm(FlaskForm):
    Author_Name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    Author_Bio = TextAreaField("Bio", validators=[Optional(), Length(max=2000)])


# --- Helpers ---
def parse_yyyymmdd(value):
    """Parse date in yyyymmdd (e.g., 20220131) or yyyy-mm-dd and return date object.
       Return (date_obj, None) on success or (None, error_msg) on failure."""
    if not value:
        return None, None
    try:
        # allow yyyymmdd or yyyy-mm-dd
        if len(value) == 8 and value.isdigit():
            dt = datetime.strptime(value, "%Y%m%d").date()
            return dt, None
        # try flexible parsing
        dt = date_parser.parse(value).date()
        return dt, None
    except Exception as e:
        return None, f"Invalid date format '{value}'. Expected 'yyyymmdd' (e.g. 20220131) or ISO format."


def api_error_single(message, status=400):
    return jsonify({"message": message}), status


def api_error_multi(errors, status=400):
    # errors: dict field -> list of messages
    return jsonify({"message": errors}), status


# --- Routes: HTML UI ---
NAV_HTML = """
<nav class="navbar navbar-expand-lg navbar-light bg-light mb-3">
  <div class="container-fluid">
    <a class="navbar-brand" href="{{ url_for('home') }}">Book Catalog</a>
    <div class="collapse navbar-collapse">
      <ul class="navbar-nav me-auto mb-2 mb-lg-0">
        <li class="nav-item"><a class="nav-link {% if active=='books' %}active{% endif %}" href="{{ url_for('books') }}">Books</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='genres' %}active{% endif %}" href="{{ url_for('genres') }}">Genres</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='authors' %}active{% endif %}" href="{{ url_for('authors') }}">Authors</a></li>
        <li class="nav-item"><a class="nav-link {% if active=='home' %}active{% endif %}" href="{{ url_for('home') }}">Home</a></li>
        <li class="nav-item"><a class="nav-link" href="{{ url_for('api_index') }}" target="_blank">API</a></li>
      </ul>
    </div>
  </div>
</nav>
"""

BASE_HTML = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Book Catalog</title>
    <!-- Bootstrap 5 CDN (allowed by Talisman script/style policy above) -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
      .small-muted { font-size: 0.9rem; color: #6c757d; }
      .table-wrap { overflow-x:auto; }
      .date-filter { display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap; }
      .date-filter input { max-width:160px; }
      .pagination { margin-top: 0.5rem; }
    </style>
  </head>
  <body class="bg-light">
    <div class="container py-4">
      {{ nav|safe }}
      <div class="card shadow-sm p-3">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for cat, msg in messages %}
              <div class="alert alert-{{cat}} alert-dismissible fade show" role="alert">
                {{ msg }}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {{ body|safe }}
      </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
      // helper: hook refresh button in date filter forms
      function submitDateFilter(formId) {
        document.getElementById(formId).submit();
      }
    </script>
  </body>
</html>
"""

@app.route("/")
def home():
    nav = render_template_string(NAV_HTML, active='home')
    body = """
    <h1>Welcome to Book Catalog</h1>
    <p class="small-muted">Use the navigation to manage Books, Genres, Authors or to access the REST API.</p>
    <div class="mt-3">
      <a class="btn btn-primary me-2" href="{{ url_for('books') }}">Books</a>
      <a class="btn btn-secondary me-2" href="{{ url_for('genres') }}">Genres</a>
      <a class="btn btn-secondary me-2" href="{{ url_for('authors') }}">Authors</a>
      <a class="btn btn-outline-dark" href="{{ url_for('api_index') }}" target="_blank">API Endpoints</a>
    </div>
    """
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string(body))


# ----- Book routes -----
@app.route("/books")
def books():
    # list books with optional date range filter and pagination
    nav = render_template_string(NAV_HTML, active='books')

    # Read date filters from query params (HTML form uses 'after' and 'before' keys)
    after_raw = request.args.get('after', '').strip()
    before_raw = request.args.get('before', '').strip()
    page = max(1, int(request.args.get('page', 1)))

    after_date, err_a = parse_yyyymmdd(after_raw) if after_raw else (None, None)
    before_date, err_b = parse_yyyymmdd(before_raw) if before_raw else (None, None)

    if err_a:
        flash(err_a, "danger")
    if err_b:
        flash(err_b, "danger")

    q = Book.query
    if after_date:
        q = q.filter(Book.Book_Publication_Date >= after_date)
    if before_date:
        q = q.filter(Book.Book_Publication_Date <= before_date)

    total = q.count()
    books = q.order_by(Book.Book_ID).offset((page-1)*PAGE_SIZE).limit(PAGE_SIZE).all()

    # pagination
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page_numbers = list(range(1, total_pages + 1))
    next_page = page + 1 if page < total_pages else None

    body = render_template_string("""
    <div class="d-flex justify-content-between align-items-center">
      <h2>Books</h2>
      <div>
        <a class="btn btn-success" href="{{ url_for('create_book') }}">Create New</a>
      </div>
    </div>

    <form id="date-filter-form" class="date-filter my-3" method="get" action="{{ url_for('books') }}">
      <div class="input-group">
        <span class="input-group-text">After</span>
        <input class="form-control" name="after" value="{{ after_raw }}" placeholder="yyyymmdd or yyyy-mm-dd" />
      </div>
      <div class="input-group">
        <span class="input-group-text">Before</span>
        <input class="form-control" name="before" value="{{ before_raw }}" placeholder="yyyymmdd or yyyy-mm-dd" />
      </div>
      <input type="hidden" name="page" value="1" />
      <div>
        <button type="submit" class="btn btn-outline-primary" title="Refresh">Refresh</button>
      </div>
    </form>

    <div class="table-wrap">
      <table class="table table-striped table-hover">
        <thead>
          <tr>
            <th>ID</th><th>Book ID</th><th>Title</th><th>Author</th><th>Genre</th><th>P_Date</th><th>Actions</th>
          </tr>
        </thead>
        <tbody>
        {% for b in books %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>{{ b.Book_ID }}</td>
            <td><a href="{{ url_for('book_details', book_id=b.Book_ID) }}">{{ b.Book_Title }}</a></td>
            <td>{{ b.Book_Author }}</td>
            <td>{{ b.Book_Genre }}</td>
            <td>{{ b.Book_Publication_Date.isoformat() if b.Book_Publication_Date else '' }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_book', book_id=b.Book_ID) }}">Update</a>
              <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_book_confirm', book_id=b.Book_ID) }}">Delete</a>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="d-flex justify-content-between align-items-center">
      <div class="small-muted">Showing {{ books|length }} of {{ total }} results</div>
      <nav>
        <ul class="pagination">
          {% for p in page_numbers %}
            <li class="page-item {% if p==page %}active{% endif %}">
              <a class="page-link" href="{{ url_for('books') }}?page={{p}}&after={{after_raw}}&before={{before_raw}}">{{p}}</a>
            </li>
          {% endfor %}
          {% if next_page %}
            <li class="page-item">
              <a class="page-link" href="{{ url_for('books') }}?page={{next_page}}&after={{after_raw}}&before={{before_raw}}">Next</a>
            </li>
          {% endif %}
        </ul>
      </nav>
    </div>
    """, books=books, total=total, page=page, page_numbers=page_numbers, next_page=next_page,
                         after_raw=after_raw, before_raw=before_raw)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/books/<int:book_id>")
def book_details(book_id):
    nav = render_template_string(NAV_HTML, active='books')
    b = Book.query.get_or_404(book_id)
    body = render_template_string("""
    <div class="d-flex justify-content-between">
      <h2>Book Details</h2>
      <div>
        <a class="btn btn-outline-primary" href="{{ url_for('edit_book', book_id=b.Book_ID) }}">Update</a>
        <a class="btn btn-outline-danger" href="{{ url_for('delete_book_confirm', book_id=b.Book_ID) }}">Delete</a>
        <a class="btn btn-secondary" href="{{ url_for('books') }}">Back to list</a>
      </div>
    </div>
    <table class="table mt-3">
      <tr><th>Book ID</th><td>{{ b.Book_ID }}</td></tr>
      <tr><th>Title</th><td>{{ b.Book_Title }}</td></tr>
      <tr><th>Author</th><td>{{ b.Book_Author }}</td></tr>
      <tr><th>Genre</th><td>{{ b.Book_Genre }}</td></tr>
      <tr><th>Description</th><td>{{ b.Book_Description }}</td></tr>
      <tr><th>Publication date</th><td>{{ b.Book_Publication_Date.isoformat() if b.Book_Publication_Date else '' }}</td></tr>
    </table>
    """, b=b)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/books/create", methods=["GET", "POST"])
def create_book():
    nav = render_template_string(NAV_HTML, active='books')
    form = BookForm()
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Creation cancelled.", "info")
            return redirect(url_for('books'))
        if form.validate_on_submit():
            # normalize date field
            dt = None
            date_raw = form.Book_Publication_Date.data.strip() if form.Book_Publication_Date.data else None
            if date_raw:
                dt, err = parse_yyyymmdd(date_raw)
                if err:
                    form.Book_Publication_Date.errors.append(err)
                    return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(), form=form, action=url_for('create_book')))
            new = Book(
                Book_Title=form.Book_Title.data.strip(),
                Book_Author=form.Book_Author.data.strip(),
                Book_Genre=form.Book_Genre.data.strip(),
                Book_Publication=form.Book_Publication.data.strip() if form.Book_Publication.data else None,
                Book_Publication_Date=dt,
                Book_Description=form.Book_Description.data.strip() if form.Book_Description.data else None
            )
            try:
                db.session.add(new)
                db.session.commit()
                flash("New book created.", "success")
                return redirect(url_for('books'))
            except Exception as e:
                db.session.rollback()
                flash("Error creating book: " + str(e), "danger")
                return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(), form=form, action=url_for('create_book')))
        else:
            flash("Please correct the errors and try again.", "danger")
    # GET
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(), form=form, action=url_for('create_book')))


@app.route("/books/<int:book_id>/edit", methods=["GET", "POST"])
def edit_book(book_id):
    nav = render_template_string(NAV_HTML, active='books')
    b = Book.query.get_or_404(book_id)
    form = BookForm(obj=b)
    # populate date field formatted as yyyy-mm-dd
    if request.method == "GET":
        form.Book_Publication_Date.data = b.Book_Publication_Date.isoformat() if b.Book_Publication_Date else ""
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Update cancelled.", "info")
            return redirect(url_for('books'))
        if form.validate_on_submit():
            date_raw = form.Book_Publication_Date.data.strip() if form.Book_Publication_Date.data else None
            dt = None
            if date_raw:
                dt, err = parse_yyyymmdd(date_raw)
                if err:
                    form.Book_Publication_Date.errors.append(err)
                    return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(edit=True), form=form, action=url_for('edit_book', book_id=book_id)))
            b.Book_Title = form.Book_Title.data.strip()
            b.Book_Author = form.Book_Author.data.strip()
            b.Book_Genre = form.Book_Genre.data.strip()
            b.Book_Publication = form.Book_Publication.data.strip() if form.Book_Publication.data else None
            b.Book_Publication_Date = dt
            b.Book_Description = form.Book_Description.data.strip() if form.Book_Description.data else None
            try:
                db.session.commit()
                flash("Book updated.", "success")
                return redirect(url_for('books'))
            except Exception as e:
                db.session.rollback()
                flash("Error updating book: " + str(e), "danger")
                return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(edit=True), form=form, action=url_for('edit_book', book_id=book_id)))
        else:
            flash("Please correct the errors and try again.", "danger")
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string(_book_form_template(edit=True), form=form, action=url_for('edit_book', book_id=book_id)))


@app.route("/books/<int:book_id>/delete", methods=["GET", "POST"])
def delete_book_confirm(book_id):
    nav = render_template_string(NAV_HTML, active='books')
    b = Book.query.get_or_404(book_id)
    if request.method == "POST":
        if 'confirm' in request.form:
            try:
                db.session.delete(b)
                db.session.commit()
                flash("Book deleted.", "success")
                return redirect(url_for('books'))
            except Exception as e:
                db.session.rollback()
                flash("Error deleting book: " + str(e), "danger")
                return redirect(url_for('books'))
        else:
            flash("Deletion cancelled.", "info")
            return redirect(url_for('books'))
    body = render_template_string("""
    <h3>Confirm delete</h3>
    <p>Are you sure you want to delete the book <strong>{{ b.Book_Title }}</strong> (ID {{ b.Book_ID }})?</p>
    <form method="post">
      {{ csrf_token() }}
      <button name="confirm" class="btn btn-danger">Confirm</button>
      <button name="cancel" class="btn btn-secondary">Cancel</button>
    </form>
    """, b=b)
    return render_template_string(BASE_HTML, nav=nav, body=body)


def _book_form_template(edit=False):
    heading = "Edit Book" if edit else "Create Book"
    return f"""
    <h3>{heading}</h3>
    <form method="post" novalidate>
      {{% with %}}{{{{}}}}{{% endwith %}}
      {{% csrf_token() %}}
      <div class="mb-3">
        {{ form.Book_Title.label }}{{ form.Book_Title(class_="form-control") }}
        {{% for e in form.Book_Title.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div class="mb-3">
        {{ form.Book_Author.label }}{{ form.Book_Author(class_="form-control") }}
        {{% for e in form.Book_Author.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div class="mb-3">
        {{ form.Book_Genre.label }}{{ form.Book_Genre(class_="form-control") }}
        {{% for e in form.Book_Genre.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div class="mb-3">
        {{ form.Book_Publication.label }}{{ form.Book_Publication(class_="form-control") }}
        {{% for e in form.Book_Publication.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div class="mb-3">
        {{ form.Book_Publication_Date.label }}{{ form.Book_Publication_Date(class_="form-control") }}
        <div class="small-muted">Accepts yyyymmdd or yyyy-mm-dd</div>
        {{% for e in form.Book_Publication_Date.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div class="mb-3">
        {{ form.Book_Description.label }}{{ form.Book_Description(class_="form-control", rows=4) }}
        {{% for e in form.Book_Description.errors %}}<div class="text-danger small">{{{{ e }}}}</div>{{% endfor %}}
      </div>
      <div>
        <button name="submit" class="btn btn-primary" type="submit">Submit</button>
        <button name="cancel" class="btn btn-secondary" type="submit">Cancel</button>
        <a class="btn btn-light" href="{{{{ url_for('books') }}}}">Back</a>
      </div>
    </form>
    """


# ----- Genres -----
@app.route("/genres")
def genres():
    nav = render_template_string(NAV_HTML, active='genres')
    page = max(1, int(request.args.get('page', 1)))
    per_page = 20  # "up to items on each page" — choose 20 for genres/authors
    q = Genre.query.order_by(Genre.Genre_ID)
    total = q.count()
    items = q.offset((page-1)*per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page_numbers = list(range(1, total_pages + 1))
    next_page = page + 1 if page < total_pages else None
    body = render_template_string("""
    <div class="d-flex justify-content-between">
      <h2>Genres</h2>
      <a class="btn btn-success" href="{{ url_for('create_genre') }}">Create new</a>
    </div>
    <div class="table-wrap mt-3">
      <table class="table table-striped">
        <thead><tr><th>ID</th><th>Genre ID</th><th>Name</th><th>Description</th><th>Actions</th></tr></thead>
        <tbody>
        {% for g in items %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>{{ g.Genre_ID }}</td>
            <td><a href="{{ url_for('genre_details', genre_id=g.Genre_ID) }}">{{ g.Genre_Name }}</a></td>
            <td>{{ g.Genre_Description }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_genre', genre_id=g.Genre_ID) }}">Update</a>
              <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_genre_confirm', genre_id=g.Genre_ID) }}">Delete</a>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="d-flex justify-content-between">
      <div class="small-muted">Showing {{ items|length }} of {{ total }}</div>
      <nav>
        <ul class="pagination">
          {% for p in page_numbers %}
            <li class="page-item {% if p==page %}active{% endif %}">
              <a class="page-link" href="{{ url_for('genres') }}?page={{p}}">{{p}}</a>
            </li>
          {% endfor %}
          {% if next_page %}
            <li class="page-item"><a class="page-link" href="{{ url_for('genres') }}?page={{next_page}}">Next</a></li>
          {% endif %}
        </ul>
      </nav>
    </div>
    """, items=items, total=total, page=page, page_numbers=page_numbers, next_page=next_page)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/genres/<int:genre_id>")
def genre_details(genre_id):
    nav = render_template_string(NAV_HTML, active='genres')
    g = Genre.query.get_or_404(genre_id)
    body = render_template_string("""
    <div class="d-flex justify-content-between">
      <h2>Genre Details</h2>
      <div>
        <a class="btn btn-outline-primary" href="{{ url_for('edit_genre', genre_id=g.Genre_ID) }}">Update</a>
        <a class="btn btn-outline-danger" href="{{ url_for('delete_genre_confirm', genre_id=g.Genre_ID) }}">Delete</a>
        <a class="btn btn-secondary" href="{{ url_for('genres') }}">Back to list</a>
      </div>
    </div>
    <table class="table mt-3">
      <tr><th>Genre ID</th><td>{{ g.Genre_ID }}</td></tr>
      <tr><th>Name</th><td>{{ g.Genre_Name }}</td></tr>
      <tr><th>Description</th><td>{{ g.Genre_Description }}</td></tr>
    </table>
    """, g=g)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/genres/create", methods=["GET", "POST"])
def create_genre():
    nav = render_template_string(NAV_HTML, active='genres')
    form = GenreForm()
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Creation cancelled.", "info")
            return redirect(url_for('genres'))
        if form.validate_on_submit():
            new = Genre(
                Genre_Name=form.Genre_Name.data.strip(),
                Genre_Description=form.Genre_Description.data.strip() if form.Genre_Description.data else None
            )
            try:
                db.session.add(new)
                db.session.commit()
                flash("New genre created.", "success")
                return redirect(url_for('genres'))
            except Exception as e:
                db.session.rollback()
                flash("Error creating genre: " + str(e), "danger")
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Create genre</h3>
      <form method="post">
        {{ csrf_token() }}
        <div class="mb-3">{{ form.Genre_Name.label }}{{ form.Genre_Name(class_='form-control') }}{% for e in form.Genre_Name.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <div class="mb-3">{{ form.Genre_Description.label }}{{ form.Genre_Description(class_='form-control', rows=3) }}{% for e in form.Genre_Description.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <button name="submit" class="btn btn-primary" type="submit">Submit</button>
        <button name="cancel" class="btn btn-secondary" type="submit">Cancel</button>
        <a class="btn btn-light" href="{{ url_for('genres') }}">Back</a>
      </form>
    """, form=form))


@app.route("/genres/<int:genre_id>/edit", methods=["GET", "POST"])
def edit_genre(genre_id):
    nav = render_template_string(NAV_HTML, active='genres')
    g = Genre.query.get_or_404(genre_id)
    form = GenreForm(obj=g)
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Update cancelled.", "info")
            return redirect(url_for('genres'))
        if form.validate_on_submit():
            g.Genre_Name = form.Genre_Name.data.strip()
            g.Genre_Description = form.Genre_Description.data.strip() if form.Genre_Description.data else None
            try:
                db.session.commit()
                flash("Genre updated.", "success")
                return redirect(url_for('genres'))
            except Exception as e:
                db.session.rollback()
                flash("Error updating genre: " + str(e), "danger")
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Edit genre</h3>
      <form method="post">
        {{ csrf_token() }}
        <div class="mb-3">{{ form.Genre_Name.label }}{{ form.Genre_Name(class_='form-control') }}{% for e in form.Genre_Name.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <div class="mb-3">{{ form.Genre_Description.label }}{{ form.Genre_Description(class_='form-control', rows=3) }}{% for e in form.Genre_Description.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <button class="btn btn-primary" type="submit">Submit</button>
        <button name="cancel" class="btn btn-secondary" type="submit">Cancel</button>
        <a class="btn btn-light" href="{{ url_for('genres') }}">Back</a>
      </form>
    """, form=form))


@app.route("/genres/<int:genre_id>/delete", methods=["GET", "POST"])
def delete_genre_confirm(genre_id):
    nav = render_template_string(NAV_HTML, active='genres')
    g = Genre.query.get_or_404(genre_id)
    if request.method == "POST":
        if 'confirm' in request.form:
            try:
                db.session.delete(g)
                db.session.commit()
                flash("Genre deleted.", "success")
                return redirect(url_for('genres'))
            except Exception as e:
                db.session.rollback()
                flash("Error deleting genre: " + str(e), "danger")
                return redirect(url_for('genres'))
        else:
            flash("Deletion cancelled.", "info")
            return redirect(url_for('genres'))
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Confirm delete</h3>
      <p>Delete genre <strong>{{ g.Genre_Name }}</strong>?</p>
      <form method="post">
        {{ csrf_token() }}
        <button name="confirm" class="btn btn-danger">Confirm</button>
        <button name="cancel" class="btn btn-secondary">Cancel</button>
      </form>
    """, g=g))


# ----- Authors -----
@app.route("/authors")
def authors():
    nav = render_template_string(NAV_HTML, active='authors')
    page = max(1, int(request.args.get('page', 1)))
    per_page = 20
    q = Author.query.order_by(Author.Author_ID)
    total = q.count()
    items = q.offset((page-1)*per_page).limit(per_page).all()
    total_pages = max(1, (total + per_page - 1) // per_page)
    page_numbers = list(range(1, total_pages + 1))
    next_page = page + 1 if page < total_pages else None
    body = render_template_string("""
    <div class="d-flex justify-content-between">
      <h2>Authors</h2>
      <a class="btn btn-success" href="{{ url_for('create_author') }}">Create new</a>
    </div>
    <div class="table-wrap mt-3">
      <table class="table table-striped">
        <thead><tr><th>ID</th><th>Author ID</th><th>Name</th><th>Bio</th><th>Actions</th></tr></thead>
        <tbody>
        {% for a in items %}
          <tr>
            <td>{{ loop.index }}</td>
            <td>{{ a.Author_ID }}</td>
            <td><a href="{{ url_for('author_details', author_id=a.Author_ID) }}">{{ a.Author_Name }}</a></td>
            <td>{{ a.Author_Bio }}</td>
            <td>
              <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit_author', author_id=a.Author_ID) }}">Update</a>
              <a class="btn btn-sm btn-outline-danger" href="{{ url_for('delete_author_confirm', author_id=a.Author_ID) }}">Delete</a>
            </td>
          </tr>
        {% endfor %}
        </tbody>
      </table>
    </div>
    <div class="d-flex justify-content-between">
      <div class="small-muted">Showing {{ items|length }} of {{ total }}</div>
      <nav>
        <ul class="pagination">
          {% for p in page_numbers %}
            <li class="page-item {% if p==page %}active{% endif %}">
              <a class="page-link" href="{{ url_for('authors') }}?page={{p}}">{{p}}</a>
            </li>
          {% endfor %}
          {% if next_page %}
            <li class="page-item"><a class="page-link" href="{{ url_for('authors') }}?page={{next_page}}">Next</a></li>
          {% endif %}
        </ul>
      </nav>
    </div>
    """, items=items, total=total, page=page, page_numbers=page_numbers, next_page=next_page)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/authors/<int:author_id>")
def author_details(author_id):
    nav = render_template_string(NAV_HTML, active='authors')
    a = Author.query.get_or_404(author_id)
    body = render_template_string("""
    <div class="d-flex justify-content-between">
      <h2>Author Details</h2>
      <div>
        <a class="btn btn-outline-primary" href="{{ url_for('edit_author', author_id=a.Author_ID) }}">Update</a>
        <a class="btn btn-outline-danger" href="{{ url_for('delete_author_confirm', author_id=a.Author_ID) }}">Delete</a>
        <a class="btn btn-secondary" href="{{ url_for('authors') }}">Back to list</a>
      </div>
    </div>
    <table class="table mt-3">
      <tr><th>Author ID</th><td>{{ a.Author_ID }}</td></tr>
      <tr><th>Name</th><td>{{ a.Author_Name }}</td></tr>
      <tr><th>Bio</th><td>{{ a.Author_Bio }}</td></tr>
    </table>
    """, a=a)
    return render_template_string(BASE_HTML, nav=nav, body=body)


@app.route("/authors/create", methods=["GET", "POST"])
def create_author():
    nav = render_template_string(NAV_HTML, active='authors')
    form = AuthorForm()
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Creation cancelled.", "info")
            return redirect(url_for('authors'))
        if form.validate_on_submit():
            new = Author(
                Author_Name=form.Author_Name.data.strip(),
                Author_Bio=form.Author_Bio.data.strip() if form.Author_Bio.data else None
            )
            try:
                db.session.add(new)
                db.session.commit()
                flash("New author created.", "success")
                return redirect(url_for('authors'))
            except Exception as e:
                db.session.rollback()
                flash("Error creating author: " + str(e), "danger")
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Create author</h3>
      <form method="post">
        {{ csrf_token() }}
        <div class="mb-3">{{ form.Author_Name.label }}{{ form.Author_Name(class_='form-control') }}{% for e in form.Author_Name.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <div class="mb-3">{{ form.Author_Bio.label }}{{ form.Author_Bio(class_='form-control', rows=3) }}{% for e in form.Author_Bio.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <button name="submit" class="btn btn-primary" type="submit">Submit</button>
        <button name="cancel" class="btn btn-secondary" type="submit">Cancel</button>
        <a class="btn btn-light" href="{{ url_for('authors') }}">Back</a>
      </form>
    """, form=form))


@app.route("/authors/<int:author_id>/edit", methods=["GET", "POST"])
def edit_author(author_id):
    nav = render_template_string(NAV_HTML, active='authors')
    a = Author.query.get_or_404(author_id)
    form = AuthorForm(obj=a)
    if request.method == "POST":
        if 'cancel' in request.form:
            flash("Update cancelled.", "info")
            return redirect(url_for('authors'))
        if form.validate_on_submit():
            a.Author_Name = form.Author_Name.data.strip()
            a.Author_Bio = form.Author_Bio.data.strip() if form.Author_Bio.data else None
            try:
                db.session.commit()
                flash("Author updated.", "success")
                return redirect(url_for('authors'))
            except Exception as e:
                db.session.rollback()
                flash("Error updating author: " + str(e), "danger")
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Edit author</h3>
      <form method="post">
        {{ csrf_token() }}
        <div class="mb-3">{{ form.Author_Name.label }}{{ form.Author_Name(class_='form-control') }}{% for e in form.Author_Name.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <div class="mb-3">{{ form.Author_Bio.label }}{{ form.Author_Bio(class_='form-control', rows=3) }}{% for e in form.Author_Bio.errors %}<div class="text-danger small">{{ e }}</div>{% endfor %}</div>
        <button class="btn btn-primary" type="submit">Submit</button>
        <button name="cancel" class="btn btn-secondary" type="submit">Cancel</button>
        <a class="btn btn-light" href="{{ url_for('authors') }}">Back</a>
      </form>
    """, form=form))


@app.route("/authors/<int:author_id>/delete", methods=["GET", "POST"])
def delete_author_confirm(author_id):
    nav = render_template_string(NAV_HTML, active='authors')
    a = Author.query.get_or_404(author_id)
    if request.method == "POST":
        if 'confirm' in request.form:
            try:
                db.session.delete(a)
                db.session.commit()
                flash("Author deleted.", "success")
                return redirect(url_for('authors'))
            except Exception as e:
                db.session.rollback()
                flash("Error deleting author: " + str(e), "danger")
                return redirect(url_for('authors'))
        else:
            flash("Deletion cancelled.", "info")
            return redirect(url_for('authors'))
    return render_template_string(BASE_HTML, nav=nav, body=render_template_string("""
      <h3>Confirm delete</h3>
      <p>Delete author <strong>{{ a.Author_Name }}</strong>?</p>
      <form method="post">
        {{ csrf_token() }}
        <button name="confirm" class="btn btn-danger">Confirm</button>
        <button name="cancel" class="btn btn-secondary">Cancel</button>
      </form>
    """, a=a))


# ----- API index (simple) -----
@app.route("/api")
def api_index():
    # minimal API docs (HTML)
    nav = ""  # API nav purposely omitted (per spec "except for API")
    body = """
    <h2>Book Catalog API (v)</h2>
    <p>Base: <code>/api/v/</code></p>
    <ul>
      <li>Books:
        <ul>
          <li>GET /api/v/books?after_date=yyyymmdd&before_date=yyyymmdd&limit=&offset=</li>
          <li>GET /api/v/books/&lt;book_id&gt;</li>
          <li>POST /api/v/books</li>
          <li>PUT /api/v/books/&lt;book_id&gt;</li>
          <li>DELETE /api/v/books/&lt;book_id&gt;</li>
        </ul>
      </li>
      <li>Genres and Authors follow the same pattern under /api/v/genres and /api/v/authors</li>
    </ul>
    <p>API returns JSON. Date in API query params should be <code>yyyymmdd</code> or ISO format. POST/PUT bodies should be JSON with matching attribute names (e.g. <code>Book_Title</code>).</p>
    """
    return render_template_string(BASE_HTML, nav=nav, body=body)


# ----- Helpers for parsing JSON bodies safely -----
def get_json_field(data, name, required=False, maxlen=None):
    val = data.get(name)
    if val is None:
        if required:
            return None, f"Field '{name}' is required."
        return None, None
    if isinstance(val, str):
        s = val.strip()
    else:
        s = val
    if maxlen and isinstance(s, str) and len(s) > maxlen:
        return None, f"Field '{name}' is too long (max {maxlen})."
    return s, None


# ----- API: Books -----
@app.route("/api/v/books", methods=["GET", "POST"])
def api_books():
    if request.method == "GET":
        # Support before_date, after_date in yyyymmdd format
        before_raw = request.args.get('before_date') or request.args.get('before')
        after_raw = request.args.get('after_date') or request.args.get('after')
        limit_raw = request.args.get('limit', type=int)
        offset_raw = request.args.get('offset', type=int) or 0

        before_date, err_b = parse_yyyymmdd(before_raw) if before_raw else (None, None)
        after_date, err_a = parse_yyyymmdd(after_raw) if after_raw else (None, None)
        if err_a:
            return api_error_single(err_a, 400)
        if err_b:
            return api_error_single(err_b, 400)

        q = Book.query
        if after_date:
            q = q.filter(Book.Book_Publication_Date >= after_date)
        if before_date:
            q = q.filter(Book.Book_Publication_Date <= before_date)
        q = q.order_by(Book.Book_ID)
        if limit_raw and limit_raw > 0:
            q = q.limit(limit_raw)
        if offset_raw and offset_raw > 0:
            q = q.offset(offset_raw)
        rows = q.all()
        return jsonify([r.to_dict() for r in rows]), 200

    # POST create
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    # required: Book_Title, Book_Author, Book_Genre
    errors = {}
    title, e = get_json_field(data, "Book_Title", required=True, maxlen=300)
    if e: errors.setdefault("Book_Title", []).append(e)
    author, e = get_json_field(data, "Book_Author", required=True, maxlen=200)
    if e: errors.setdefault("Book_Author", []).append(e)
    genre, e = get_json_field(data, "Book_Genre", required=True, maxlen=120)
    if e: errors.setdefault("Book_Genre", []).append(e)
    publication, e = get_json_field(data, "Book_Publication", required=False, maxlen=200)
    if e: errors.setdefault("Book_Publication", []).append(e)
    pubdate_raw, e = get_json_field(data, "Book_Publication_Date", required=False)
    if e: errors.setdefault("Book_Publication_Date", []).append(e)
    description, e = get_json_field(data, "Book_Description", required=False, maxlen=5000)
    if e: errors.setdefault("Book_Description", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    pubdate = None
    if pubdate_raw:
        pubdate, err = parse_yyyymmdd(str(pubdate_raw))
        if err:
            return api_error_single(err, 400)
    new = Book(
        Book_Title=title,
        Book_Author=author,
        Book_Genre=genre,
        Book_Publication=publication,
        Book_Publication_Date=pubdate,
        Book_Description=description
    )
    try:
        db.session.add(new)
        db.session.commit()
        return jsonify(new.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


@app.route("/api/v/books/<int:book_id>", methods=["GET", "PUT", "DELETE"])
def api_book_detail(book_id):
    b = Book.query.get(book_id)
    if not b:
        return api_error_single("Book not found", 404)
    if request.method == "GET":
        return jsonify(b.to_dict()), 200
    if request.method == "DELETE":
        try:
            db.session.delete(b)
            db.session.commit()
            # per spec: empty JSON body for successful deletion
            return jsonify({}), 200
        except Exception as e:
            db.session.rollback()
            return api_error_single(str(e), 500)
    # PUT update
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    errors = {}
    title, e = get_json_field(data, "Book_Title", required=False, maxlen=300)
    if e: errors.setdefault("Book_Title", []).append(e)
    author, e = get_json_field(data, "Book_Author", required=False, maxlen=200)
    if e: errors.setdefault("Book_Author", []).append(e)
    genre, e = get_json_field(data, "Book_Genre", required=False, maxlen=120)
    if e: errors.setdefault("Book_Genre", []).append(e)
    publication, e = get_json_field(data, "Book_Publication", required=False, maxlen=200)
    if e: errors.setdefault("Book_Publication", []).append(e)
    pubdate_raw, e = get_json_field(data, "Book_Publication_Date", required=False)
    if e: errors.setdefault("Book_Publication_Date", []).append(e)
    description, e = get_json_field(data, "Book_Description", required=False, maxlen=5000)
    if e: errors.setdefault("Book_Description", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    if title is not None:
        b.Book_Title = title
    if author is not None:
        b.Book_Author = author
    if genre is not None:
        b.Book_Genre = genre
    if publication is not None:
        b.Book_Publication = publication
    if description is not None:
        b.Book_Description = description
    if pubdate_raw is not None:
        if pubdate_raw == "":
            b.Book_Publication_Date = None
        else:
            pubdate, err = parse_yyyymmdd(str(pubdate_raw))
            if err:
                return api_error_single(err, 400)
            b.Book_Publication_Date = pubdate
    try:
        db.session.commit()
        return jsonify(b.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


# ----- API: Genres -----
@app.route("/api/v/genres", methods=["GET", "POST"])
def api_genres():
    if request.method == "GET":
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int) or 0
        q = Genre.query.order_by(Genre.Genre_ID)
        if offset:
            q = q.offset(offset)
        if limit:
            q = q.limit(limit)
        rows = q.all()
        return jsonify([r.to_dict() for r in rows]), 200
    # POST
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    errors = {}
    name, e = get_json_field(data, "Genre_Name", required=True, maxlen=120)
    if e: errors.setdefault("Genre_Name", []).append(e)
    desc, e = get_json_field(data, "Genre_Description", required=False, maxlen=1000)
    if e: errors.setdefault("Genre_Description", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    new = Genre(Genre_Name=name, Genre_Description=desc)
    try:
        db.session.add(new)
        db.session.commit()
        return jsonify(new.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


@app.route("/api/v/genres/<int:genre_id>", methods=["GET", "PUT", "DELETE"])
def api_genre_detail(genre_id):
    g = Genre.query.get(genre_id)
    if not g:
        return api_error_single("Genre not found", 404)
    if request.method == "GET":
        return jsonify(g.to_dict()), 200
    if request.method == "DELETE":
        try:
            db.session.delete(g)
            db.session.commit()
            return jsonify({}), 200
        except Exception as e:
            db.session.rollback()
            return api_error_single(str(e), 500)
    # PUT
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    errors = {}
    name, e = get_json_field(data, "Genre_Name", required=False, maxlen=120)
    if e: errors.setdefault("Genre_Name", []).append(e)
    desc, e = get_json_field(data, "Genre_Description", required=False, maxlen=1000)
    if e: errors.setdefault("Genre_Description", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    if name is not None:
        g.Genre_Name = name
    if desc is not None:
        g.Genre_Description = desc
    try:
        db.session.commit()
        return jsonify(g.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


# ----- API: Authors -----
@app.route("/api/v/authors", methods=["GET", "POST"])
def api_authors():
    if request.method == "GET":
        limit = request.args.get('limit', type=int)
        offset = request.args.get('offset', type=int) or 0
        q = Author.query.order_by(Author.Author_ID)
        if offset:
            q = q.offset(offset)
        if limit:
            q = q.limit(limit)
        rows = q.all()
        return jsonify([r.to_dict() for r in rows]), 200
    # POST
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    errors = {}
    name, e = get_json_field(data, "Author_Name", required=True, maxlen=200)
    if e: errors.setdefault("Author_Name", []).append(e)
    bio, e = get_json_field(data, "Author_Bio", required=False, maxlen=2000)
    if e: errors.setdefault("Author_Bio", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    new = Author(Author_Name=name, Author_Bio=bio)
    try:
        db.session.add(new)
        db.session.commit()
        return jsonify(new.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


@app.route("/api/v/authors/<int:author_id>", methods=["GET", "PUT", "DELETE"])
def api_author_detail(author_id):
    a = Author.query.get(author_id)
    if not a:
        return api_error_single("Author not found", 404)
    if request.method == "GET":
        return jsonify(a.to_dict()), 200
    if request.method == "DELETE":
        try:
            db.session.delete(a)
            db.session.commit()
            return jsonify({}), 200
        except Exception as e:
            db.session.rollback()
            return api_error_single(str(e), 500)
    # PUT
    if not request.is_json:
        return api_error_single("Request must have Content-Type: application/json", 415)
    data = request.get_json()
    errors = {}
    name, e = get_json_field(data, "Author_Name", required=False, maxlen=200)
    if e: errors.setdefault("Author_Name", []).append(e)
    bio, e = get_json_field(data, "Author_Bio", required=False, maxlen=2000)
    if e: errors.setdefault("Author_Bio", []).append(e)
    if errors:
        return api_error_multi(errors, 400)
    if name is not None:
        a.Author_Name = name
    if bio is not None:
        a.Author_Bio = bio
    try:
        db.session.commit()
        return jsonify(a.to_dict()), 200
    except Exception as e:
        db.session.rollback()
        return api_error_single(str(e), 500)


# --- Initialize DB and sample data if empty ---
def seed_if_empty():
    db.create_all()
    if Genre.query.count() == 0:
        g1 = Genre(Genre_Name="Fiction", Genre_Description="Fictional works")
        g2 = Genre(Genre_Name="Non-Fiction", Genre_Description="Non-fictional works")
        db.session.add_all([g1, g2])
    if Author.query.count() == 0:
        a1 = Author(Author_Name="Jane Doe", Author_Bio="An exemplary author.")
        a2 = Author(Author_Name="John Smith", Author_Bio="Another author.")
        db.session.add_all([a1, a2])
    if Book.query.count() == 0:
        b1 = Book(Book_Title="First Book", Book_Author="Jane Doe", Book_Genre="Fiction",
                  Book_Publication="FirstPub", Book_Publication_Date=datetime(2020, 1, 15).date(),
                  Book_Description="A sample first book.")
        b2 = Book(Book_Title="Second Book", Book_Author="John Smith", Book_Genre="Non-Fiction",
                  Book_Publication="SecondPub", Book_Publication_Date=datetime(2021, 6, 1).date(),
                  Book_Description="A sample second book.")
        db.session.add_all([b1, b2])
    try:
        db.session.commit()
    except:
        db.session.rollback()


if __name__ == "__main__":
    seed_if_empty()
    # Use debug=False in production. This file is ready to run; consider using gunicorn for production.
    app.run(host="0.0.0.0", port=5000, debug=True)

