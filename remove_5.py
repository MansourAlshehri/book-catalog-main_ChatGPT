#!/usr/bin/env python3
"""
Book Catalog single-file Flask application.

Features:
- Books / Genres / Authors CRUD (HTML + REST JSON API)
- Pagination (default page size 10) and "Next"/page numbers
- Filter books by publication date range in HTML form and REST API
- REST endpoints: /api/v/books, /api/v/books/<id>, ... for genres & authors
- Date format for API date filters: yyyymmdd (e.g. 20250131)
- CSRF protection on HTML forms (Flask-WTF)
- Input validation using WTForms
- SQLAlchemy ORM (parameterized queries)
- Templates embedded in the file using render_template_string
- Confirmation page for deletions (HTML flow)
- Proper HTTP status codes and JSON error format matching your spec
"""

import os
from datetime import datetime
from flask import (
    Flask, request, jsonify, render_template_string, redirect, url_for, flash, abort
)
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, TextAreaField, DateField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length, Optional
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import SQLAlchemyError
from math import ceil

# -----------------------
# Configuration
# -----------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, "bookcatalog.db")

app = Flask(__name__)
# SECURITY: set a secure random key in production via env var
app.config['SECRET_KEY'] = os.environ.get('BOOKCATALOG_SECRET') or 'change-this-secret-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = "sqlite:///" + DATABASE_PATH
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# Default pagination size for HTML views & API
DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# -----------------------
# Models
# -----------------------
class Genre(db.Model):
    __tablename__ = 'genres'
    Genre_ID = db.Column(db.Integer, primary_key=True)
    Genre_Name = db.Column(db.String(200), nullable=False, unique=True)
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
    Book_Title = db.Column(db.String(500), nullable=False)
    Book_Author = db.Column(db.String(200), nullable=False)
    Book_Genre = db.Column(db.String(200), nullable=False)
    Book_Publication = db.Column(db.String(500), nullable=True)
    Book_Publication_Date = db.Column(db.Date, nullable=True)
    Book_Description = db.Column(db.String(5000), nullable=True)

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


# -----------------------
# Forms
# -----------------------
class BookForm(FlaskForm):
    Book_Title = StringField("Title", validators=[DataRequired(), Length(max=500)])
    Book_Author = StringField("Author", validators=[DataRequired(), Length(max=200)])
    Book_Genre = StringField("Genre", validators=[DataRequired(), Length(max=200)])
    Book_Publication = StringField("Publication", validators=[Optional(), Length(max=500)])
    Book_Publication_Date = DateField("Publication date (YYYY-MM-DD)", format="%Y-%m-%d", validators=[Optional()])
    Book_Description = TextAreaField("Description", validators=[Optional(), Length(max=5000)])
    submit = SubmitField("Submit")
    cancel = SubmitField("Cancel")


class GenreForm(FlaskForm):
    Genre_Name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    Genre_Description = TextAreaField("Description", validators=[Optional(), Length(max=1000)])
    submit = SubmitField("Submit")
    cancel = SubmitField("Cancel")


class AuthorForm(FlaskForm):
    Author_Name = StringField("Name", validators=[DataRequired(), Length(max=200)])
    Author_Bio = TextAreaField("Bio", validators=[Optional(), Length(max=2000)])
    submit = SubmitField("Submit")
    cancel = SubmitField("Cancel")


# -----------------------
# Utility helpers
# -----------------------
def api_error(message, status=400):
    """Return JSON error format matching the spec."""
    return jsonify({"message": message}), status


def api_multi_errors(errors_dict, status=400):
    # errors_dict should be {field: [messages]}
    return jsonify({"message": {k: v for k, v in errors_dict.items()}}), status


def parse_api_date(yyyymmdd: str):
    """Parse yyyymmdd into date object. Returns (date, None) or (None, error string)."""
    try:
        if len(yyyymmdd) != 8:
            raise ValueError("date must be in yyyymmdd format")
        return datetime.strptime(yyyymmdd, "%Y%m%d").date(), None
    except Exception as e:
        return None, str(e)


# -----------------------
# Templates (embedded)
# -----------------------
NAV_HTML = """
<nav style="background:#f2f2f2;padding:10px;margin-bottom:20px;">
    <a href="{{ url_for('home') }}">Home</a> |
    <a href="{{ url_for('books_list') }}">Books</a> |
    <a href="{{ url_for('genres_list') }}">Genres</a> |
    <a href="{{ url_for('authors_list') }}">Authors</a> |
    <a href="{{ url_for('api_index') }}">API</a>
</nav>
"""

HOME_TEMPLATE = """
<!doctype html>
<title>Book Catalog - Home</title>
{{ nav|safe }}
<h1>Welcome to the Book Catalog</h1>
<p>Use the navigation links to view and manage Books, Genres, and Authors.</p>
"""

API_INDEX_TEMPLATE = """
<!doctype html>
<title>Book Catalog API</title>
<h1>Book Catalog API (JSON)</h1>
<p>Use the REST API endpoints under <code>/api/v/</code>.</p>
<pre>
GET  /api/v/books
GET  /api/v/books/&lt;book_id&gt;
POST /api/v/books
PUT  /api/v/books/&lt;book_id&gt;
DELETE /api/v/books/&lt;book_id&gt;

Date filters:
GET /api/v/books?after_date=yyyymmdd
GET /api/v/books?before_date=yyyymmdd
GET /api/v/books?after_date=yyyymmdd&before_date=yyyymmdd

Pagination:
limit (max {max_size}), offset (0-based)

Same patterns available for /genres and /authors
</pre>
""".format(max_size=MAX_PAGE_SIZE)


BOOKS_LIST_TEMPLATE = """
<!doctype html>
<title>Books - Book Catalog</title>
{{ nav|safe }}
<h1>Books</h1>

<form method="get" action="{{ url_for('books_list') }}">
    <label for="after">After date (YYYY-MM-DD):</label>
    <input type="date" id="after" name="after" value="{{ request.args.get('after','') }}">
    <label for="before">Before date (YYYY-MM-DD):</label>
    <input type="date" id="before" name="before" value="{{ request.args.get('before','') }}">
    <button type="submit" title="Refresh">Refresh</button>
    <a href="{{ url_for('create_book') }}"><button type="button">Create New</button></a>
</form>

<table border="1" cellpadding="6" cellspacing="0" style="margin-top:10px;">
    <thead>
        <tr><th>ID</th><th>Book ID</th><th>Title</th><th>Author</th><th>Genre</th><th>P_Date</th><th>Actions</th></tr>
    </thead>
    <tbody>
    {% for book in books %}
      <tr>
        <td>{{ loop.index0 + (page_offset or 0) + 1 }}</td>
        <td>{{ book.Book_ID }}</td>
        <td><a href="{{ url_for('book_details', book_id=book.Book_ID) }}">{{ book.Book_Title }}</a></td>
        <td>{{ book.Book_Author }}</td>
        <td>{{ book.Book_Genre }}</td>
        <td>{{ book.Book_Publication_Date.strftime('%Y-%m-%d') if book.Book_Publication_Date else '' }}</td>
        <td>
            <a href="{{ url_for('edit_book', book_id=book.Book_ID) }}">Update</a> |
            <a href="{{ url_for('confirm_delete_book', book_id=book.Book_ID) }}">Delete</a>
        </td>
      </tr>
    {% endfor %}
    </tbody>
</table>

<div style="margin-top:10px;">
  {% if page > 1 %}
    <a href="{{ url_for('books_list', page=page-1, after=request.args.get('after'), before=request.args.get('before')) }}">Prev</a>
  {% endif %}
  Page {{ page }} of {{ total_pages }}
  {% if page < total_pages %}
    <a href="{{ url_for('books_list', page=page+1, after=request.args.get('after'), before=request.args.get('before')) }}">Next</a>
  {% endif %}
</div>
"""

BOOK_DETAILS_TEMPLATE = """
<!doctype html>
<title>Book Details</title>
{{ nav|safe }}
<h1>Book Details</h1>
<table border="1" cellpadding="6">
  <tr><th>ID</th><td>{{ book.Book_ID }}</td></tr>
  <tr><th>Title</th><td>{{ book.Book_Title }}</td></tr>
  <tr><th>Author</th><td>{{ book.Book_Author }}</td></tr>
  <tr><th>Genre</th><td>{{ book.Book_Genre }}</td></tr>
  <tr><th>Description</th><td>{{ book.Book_Description }}</td></tr>
  <tr><th>Publication date</th><td>{{ book.Book_Publication_Date.strftime('%Y-%m-%d') if book.Book_Publication_Date else '' }}</td></tr>
</table>
<p>
  <a href="{{ url_for('edit_book', book_id=book.Book_ID) }}">Update</a> |
  <a href="{{ url_for('confirm_delete_book', book_id=book.Book_ID) }}">Delete</a> |
  <a href="{{ url_for('books_list') }}">Back to list</a>
</p>
"""

BOOK_FORM_TEMPLATE = """
<!doctype html>
<title>{{ title }}</title>
{{ nav|safe }}
<h1>{{ title }}</h1>

<form method="post">
  {{ form.hidden_tag() }}
  <p>
    {{ form.Book_Title.label }}<br>
    {{ form.Book_Title(size=80) }}<br>
    {% for e in form.Book_Title.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Book_Author.label }}<br>
    {{ form.Book_Author(size=60) }}<br>
    {% for e in form.Book_Author.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Book_Genre.label }}<br>
    {{ form.Book_Genre(size=40) }}<br>
    {% for e in form.Book_Genre.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Book_Publication.label }}<br>
    {{ form.Book_Publication(size=80) }}<br>
    {% for e in form.Book_Publication.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Book_Publication_Date.label }}<br>
    {{ form.Book_Publication_Date() }}<br>
    {% for e in form.Book_Publication_Date.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Book_Description.label }}<br>
    {{ form.Book_Description(rows=6, cols=80) }}<br>
    {% for e in form.Book_Description.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>

  <p>
    {{ form.submit() }}
    {{ form.cancel() }}
  </p>
</form>
<p><a href="{{ url_for('books_list') }}">Back to books</a></p>
"""

CONFIRM_DELETE_TEMPLATE = """
<!doctype html>
<title>Confirm Delete</title>
{{ nav|safe }}
<h1>Confirm Delete</h1>
<p>Are you sure you want to delete {{ type_name }}: <strong>{{ name }}</strong> ?</p>
<form method="post">
  {{ csrf_token() }}
  <button name="confirm" value="yes" type="submit">Confirm</button>
  <a href="{{ cancel_url }}"><button type="button">Cancel</button></a>
</form>
"""

# Genre templates
GENRE_LIST_TEMPLATE = """
<!doctype html>
<title>Genres</title>
{{ nav|safe }}
<h1>Genres</h1>
<a href="{{ url_for('create_genre') }}"><button type="button">Create new</button></a>
<table border="1" cellpadding="6" cellspacing="0" style="margin-top:10px;">
  <thead><tr><th>ID</th><th>Genre ID</th><th>Name</th><th>Description</th><th>Actions</th></tr></thead>
  <tbody>
  {% for g in genres %}
    <tr>
      <td>{{ loop.index0 + (page_offset or 0) + 1 }}</td>
      <td>{{ g.Genre_ID }}</td>
      <td><a href="{{ url_for('genre_details', genre_id=g.Genre_ID) }}">{{ g.Genre_Name }}</a></td>
      <td>{{ g.Genre_Description }}</td>
      <td><a href="{{ url_for('edit_genre', genre_id=g.Genre_ID) }}">Update</a> | <a href="{{ url_for('confirm_delete_genre', genre_id=g.Genre_ID) }}">Delete</a></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<div style="margin-top:10px;">
  Page {{ page }} of {{ total_pages }}
  {% if page < total_pages %}
     <a href="{{ url_for('genres_list', page=page+1) }}">Next</a>
  {% endif %}
  {% if page > 1 %}
     <a href="{{ url_for('genres_list', page=page-1) }}">Prev</a>
  {% endif %}
</div>
"""

GENRE_DETAILS_TEMPLATE = """
<!doctype html>
<title>Genre Details</title>
{{ nav|safe }}
<h1>Genre Details</h1>
<table border="1" cellpadding="6">
  <tr><th>Genre ID</th><td>{{ g.Genre_ID }}</td></tr>
  <tr><th>Name</th><td>{{ g.Genre_Name }}</td></tr>
  <tr><th>Description</th><td>{{ g.Genre_Description }}</td></tr>
</table>
<p>
  <a href="{{ url_for('edit_genre', genre_id=g.Genre_ID) }}">Update</a> |
  <a href="{{ url_for('confirm_delete_genre', genre_id=g.Genre_ID) }}">Delete</a> |
  <a href="{{ url_for('genres_list') }}">Back to list</a>
</p>
"""

GENRE_FORM_TEMPLATE = """
<!doctype html>
<title>{{ title }}</title>
{{ nav|safe }}
<h1>{{ title }}</h1>
<form method="post">
  {{ form.hidden_tag() }}
  <p>
    {{ form.Genre_Name.label }}<br>
    {{ form.Genre_Name(size=60) }}<br>
    {% for e in form.Genre_Name.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Genre_Description.label }}<br>
    {{ form.Genre_Description(rows=6, cols=80) }}<br>
    {% for e in form.Genre_Description.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.submit() }} {{ form.cancel() }}
  </p>
</form>
<p><a href="{{ url_for('genres_list') }}">Back to genres</a></p>
"""

# Author templates
AUTHORS_LIST_TEMPLATE = """
<!doctype html>
<title>Authors</title>
{{ nav|safe }}
<h1>Authors</h1>
<a href="{{ url_for('create_author') }}"><button type="button">Create new</button></a>
<table border="1" cellpadding="6" cellspacing="0" style="margin-top:10px;">
  <thead><tr><th>ID</th><th>Author ID</th><th>Name</th><th>Bio</th><th>Actions</th></tr></thead>
  <tbody>
  {% for a in authors %}
    <tr>
      <td>{{ loop.index0 + (page_offset or 0) + 1 }}</td>
      <td>{{ a.Author_ID }}</td>
      <td><a href="{{ url_for('author_details', author_id=a.Author_ID) }}">{{ a.Author_Name }}</a></td>
      <td>{{ a.Author_Bio }}</td>
      <td><a href="{{ url_for('edit_author', author_id=a.Author_ID) }}">Update</a> | <a href="{{ url_for('confirm_delete_author', author_id=a.Author_ID) }}">Delete</a></td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<div style="margin-top:10px;">
  Page {{ page }} of {{ total_pages }}
  {% if page < total_pages %}
     <a href="{{ url_for('authors_list', page=page+1) }}">Next</a>
  {% endif %}
  {% if page > 1 %}
     <a href="{{ url_for('authors_list', page=page-1) }}">Prev</a>
  {% endif %}
</div>
"""

AUTHOR_DETAILS_TEMPLATE = """
<!doctype html>
<title>Author Details</title>
{{ nav|safe }}
<h1>Author Details</h1>
<table border="1" cellpadding="6">
  <tr><th>Author ID</th><td>{{ a.Author_ID }}</td></tr>
  <tr><th>Name</th><td>{{ a.Author_Name }}</td></tr>
  <tr><th>Bio</th><td>{{ a.Author_Bio }}</td></tr>
</table>
<p>
  <a href="{{ url_for('edit_author', author_id=a.Author_ID) }}">Update</a> |
  <a href="{{ url_for('confirm_delete_author', author_id=a.Author_ID) }}">Delete</a> |
  <a href="{{ url_for('authors_list') }}">Back to list</a>
</p>
"""

AUTHOR_FORM_TEMPLATE = """
<!doctype html>
<title>{{ title }}</title>
{{ nav|safe }}
<h1>{{ title }}</h1>
<form method="post">
  {{ form.hidden_tag() }}
  <p>
    {{ form.Author_Name.label }}<br>
    {{ form.Author_Name(size=60) }}<br>
    {% for e in form.Author_Name.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.Author_Bio.label }}<br>
    {{ form.Author_Bio(rows=6, cols=80) }}<br>
    {% for e in form.Author_Bio.errors %}<span style="color:red;">{{ e }}</span>{% endfor %}
  </p>
  <p>
    {{ form.submit() }} {{ form.cancel() }}
  </p>
</form>
<p><a href="{{ url_for('authors_list') }}">Back to authors</a></p>
"""

# -----------------------
# HTML Routes (UI)
# -----------------------

@app.route("/")
def home():
    return render_template_string(HOME_TEMPLATE, nav=NAV_HTML)


@app.route("/api")
def api_index():
    # API page: don't show the normal nav (spec said nav same for all pages except API)
    return render_template_string(API_INDEX_TEMPLATE)


# ----- Books UI -----
@app.route("/books")
def books_list():
    # Pagination & date-range filter via query params
    try:
        page = int(request.args.get('page', 1))
    except:
        page = 1
    page = max(1, page)
    limit = DEFAULT_PAGE_SIZE
    offset = (page - 1) * limit

    after_str = request.args.get('after', None)
    before_str = request.args.get('before', None)

    q = Book.query
    if after_str:
        try:
            after_date = datetime.strptime(after_str, "%Y-%m-%d").date()
            q = q.filter(Book.Book_Publication_Date >= after_date)
        except ValueError:
            flash("Invalid 'after' date format. Use YYYY-MM-DD", "error")
    if before_str:
        try:
            before_date = datetime.strptime(before_str, "%Y-%m-%d").date()
            q = q.filter(Book.Book_Publication_Date <= before_date)
        except ValueError:
            flash("Invalid 'before' date format. Use YYYY-MM-DD", "error")

    total = q.count()
    total_pages = max(1, ceil(total / limit))
    books = q.order_by(Book.Book_ID).offset(offset).limit(limit).all()

    return render_template_string(BOOKS_LIST_TEMPLATE, nav=NAV_HTML, books=books,
                                  page=page, total_pages=total_pages, page_offset=offset)


@app.route("/books/<int:book_id>")
def book_details(book_id):
    book = Book.query.get_or_404(book_id)
    return render_template_string(BOOK_DETAILS_TEMPLATE, nav=NAV_HTML, book=book)


@app.route("/books/create", methods=['GET', 'POST'])
def create_book():
    form = BookForm()
    if form.cancel.data:
        return redirect(url_for('books_list'))

    if form.validate_on_submit():
        try:
            b = Book(
                Book_Title=form.Book_Title.data.strip(),
                Book_Author=form.Book_Author.data.strip(),
                Book_Genre=form.Book_Genre.data.strip(),
                Book_Publication=form.Book_Publication.data.strip() if form.Book_Publication.data else None,
                Book_Publication_Date=form.Book_Publication_Date.data,
                Book_Description=form.Book_Description.data.strip() if form.Book_Description.data else None
            )
            db.session.add(b)
            db.session.commit()
            flash("Book created.", "success")
            return redirect(url_for('books_list'))
        except SQLAlchemyError as e:
            db.session.rollback()
            flash("Database error: could not create book.", "error")
    return render_template_string(BOOK_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Create Book")


@app.route("/books/<int:book_id>/edit", methods=['GET', 'POST'])
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    form = BookForm(obj=book)
    if form.cancel.data:
        return redirect(url_for('books_list'))

    if form.validate_on_submit():
        try:
            book.Book_Title = form.Book_Title.data.strip()
            book.Book_Author = form.Book_Author.data.strip()
            book.Book_Genre = form.Book_Genre.data.strip()
            book.Book_Publication = form.Book_Publication.data.strip() if form.Book_Publication.data else None
            book.Book_Publication_Date = form.Book_Publication_Date.data
            book.Book_Description = form.Book_Description.data.strip() if form.Book_Description.data else None
            db.session.commit()
            flash("Book updated.", "success")
            return redirect(url_for('books_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not update book.", "error")

    return render_template_string(BOOK_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Edit Book")


@app.route("/books/<int:book_id>/confirm_delete", methods=['GET', 'POST'])
def confirm_delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        try:
            db.session.delete(book)
            db.session.commit()
            flash("Book deleted.", "success")
            return redirect(url_for('books_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not delete book.", "error")
            return redirect(url_for('books_list'))
    return render_template_string(CONFIRM_DELETE_TEMPLATE, nav=NAV_HTML,
                                  type_name="Book", name=book.Book_Title,
                                  cancel_url=url_for('books_list'))


# ----- Genres UI -----
@app.route("/genres")
def genres_list():
    try:
        page = int(request.args.get('page', 1))
    except:
        page = 1
    page = max(1, page)
    limit = DEFAULT_PAGE_SIZE
    offset = (page - 1) * limit
    q = Genre.query
    total = q.count()
    total_pages = max(1, ceil(total / limit))
    genres = q.order_by(Genre.Genre_ID).offset(offset).limit(limit).all()
    return render_template_string(GENRE_LIST_TEMPLATE, nav=NAV_HTML, genres=genres, page=page, total_pages=total_pages, page_offset=offset)


@app.route("/genres/<int:genre_id>")
def genre_details(genre_id):
    g = Genre.query.get_or_404(genre_id)
    return render_template_string(GENRE_DETAILS_TEMPLATE, nav=NAV_HTML, g=g)


@app.route("/genres/create", methods=['GET', 'POST'])
def create_genre():
    form = GenreForm()
    if form.cancel.data:
        return redirect(url_for('genres_list'))
    if form.validate_on_submit():
        try:
            g = Genre(Genre_Name=form.Genre_Name.data.strip(), Genre_Description=form.Genre_Description.data.strip() if form.Genre_Description.data else None)
            db.session.add(g)
            db.session.commit()
            flash("Genre created.", "success")
            return redirect(url_for('genres_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not create genre.", "error")
    return render_template_string(GENRE_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Create Genre")


@app.route("/genres/<int:genre_id>/edit", methods=['GET', 'POST'])
def edit_genre(genre_id):
    g = Genre.query.get_or_404(genre_id)
    form = GenreForm(obj=g)
    if form.cancel.data:
        return redirect(url_for('genres_list'))
    if form.validate_on_submit():
        try:
            g.Genre_Name = form.Genre_Name.data.strip()
            g.Genre_Description = form.Genre_Description.data.strip() if form.Genre_Description.data else None
            db.session.commit()
            flash("Genre updated.", "success")
            return redirect(url_for('genres_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not update genre.", "error")
    return render_template_string(GENRE_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Edit Genre")


@app.route("/genres/<int:genre_id>/confirm_delete", methods=['GET', 'POST'])
def confirm_delete_genre(genre_id):
    g = Genre.query.get_or_404(genre_id)
    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        try:
            db.session.delete(g)
            db.session.commit()
            flash("Genre deleted.", "success")
            return redirect(url_for('genres_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not delete genre.", "error")
            return redirect(url_for('genres_list'))
    return render_template_string(CONFIRM_DELETE_TEMPLATE, nav=NAV_HTML,
                                  type_name="Genre", name=g.Genre_Name, cancel_url=url_for('genres_list'))


# ----- Authors UI -----
@app.route("/authors")
def authors_list():
    try:
        page = int(request.args.get('page', 1))
    except:
        page = 1
    page = max(1, page)
    limit = DEFAULT_PAGE_SIZE
    offset = (page - 1) * limit
    q = Author.query
    total = q.count()
    total_pages = max(1, ceil(total / limit))
    authors = q.order_by(Author.Author_ID).offset(offset).limit(limit).all()
    return render_template_string(AUTHORS_LIST_TEMPLATE, nav=NAV_HTML, authors=authors, page=page, total_pages=total_pages, page_offset=offset)


@app.route("/authors/<int:author_id>")
def author_details(author_id):
    a = Author.query.get_or_404(author_id)
    return render_template_string(AUTHOR_DETAILS_TEMPLATE, nav=NAV_HTML, a=a)


@app.route("/authors/create", methods=['GET', 'POST'])
def create_author():
    form = AuthorForm()
    if form.cancel.data:
        return redirect(url_for('authors_list'))
    if form.validate_on_submit():
        try:
            a = Author(Author_Name=form.Author_Name.data.strip(), Author_Bio=form.Author_Bio.data.strip() if form.Author_Bio.data else None)
            db.session.add(a)
            db.session.commit()
            flash("Author created.", "success")
            return redirect(url_for('authors_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not create author.", "error")
    return render_template_string(AUTHOR_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Create Author")


@app.route("/authors/<int:author_id>/edit", methods=['GET', 'POST'])
def edit_author(author_id):
    a = Author.query.get_or_404(author_id)
    form = AuthorForm(obj=a)
    if form.cancel.data:
        return redirect(url_for('authors_list'))
    if form.validate_on_submit():
        try:
            a.Author_Name = form.Author_Name.data.strip()
            a.Author_Bio = form.Author_Bio.data.strip() if form.Author_Bio.data else None
            db.session.commit()
            flash("Author updated.", "success")
            return redirect(url_for('authors_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not update author.", "error")
    return render_template_string(AUTHOR_FORM_TEMPLATE, nav=NAV_HTML, form=form, title="Edit Author")


@app.route("/authors/<int:author_id>/confirm_delete", methods=['GET', 'POST'])
def confirm_delete_author(author_id):
    a = Author.query.get_or_404(author_id)
    if request.method == 'POST' and request.form.get('confirm') == 'yes':
        try:
            db.session.delete(a)
            db.session.commit()
            flash("Author deleted.", "success")
            return redirect(url_for('authors_list'))
        except SQLAlchemyError:
            db.session.rollback()
            flash("Database error: could not delete author.", "error")
            return redirect(url_for('authors_list'))
    return render_template_string(CONFIRM_DELETE_TEMPLATE, nav=NAV_HTML,
                                  type_name="Author", name=a.Author_Name, cancel_url=url_for('authors_list'))


# -----------------------
# REST API (JSON) - versioned under /api/v/
# -----------------------
def paginate_query(query, limit, offset):
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    return total, items


# --- Books API ---
@app.route("/api/v/books", methods=['GET', 'POST'])
def api_books_collection():
    if request.method == 'GET':
        # Query params: before_date, after_date in yyyymmdd
        before_date_str = request.args.get('before_date')
        after_date_str = request.args.get('after_date')
        limit = min(int(request.args.get('limit', DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        offset = max(int(request.args.get('offset', 0)), 0)

        q = Book.query
        if after_date_str:
            dt, err = parse_api_date(after_date_str)
            if err:
                return api_error("Invalid after_date: " + err)
            q = q.filter(Book.Book_Publication_Date >= dt)
        if before_date_str:
            dt, err = parse_api_date(before_date_str)
            if err:
                return api_error("Invalid before_date: " + err)
            q = q.filter(Book.Book_Publication_Date <= dt)

        total, items = paginate_query(q.order_by(Book.Book_ID), limit, offset)
        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [i.to_dict() for i in items]
        }), 200

    # POST -> create a new book; expect JSON body
    if not request.is_json:
        return api_error("Request body must be JSON", 415)
    body = request.get_json()
    # Basic validation
    required = ['Book_Title', 'Book_Author', 'Book_Genre']
    missing = [k for k in required if not body.get(k)]
    if missing:
        return api_error(f"Missing required fields: {missing}")

    pub_date = None
    if body.get('Book_Publication_Date'):
        # Accept either yyyymmdd or YYYY-MM-DD (try both)
        raw = str(body.get('Book_Publication_Date'))
        dt = None
        for fmt in ("%Y%m%d", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt).date()
                break
            except Exception:
                pass
        if not dt:
            return api_error("Invalid Book_Publication_Date. Use yyyymmdd or YYYY-MM-DD.")
        pub_date = dt

    try:
        b = Book(
            Book_Title=str(body.get('Book_Title')).strip(),
            Book_Author=str(body.get('Book_Author')).strip(),
            Book_Genre=str(body.get('Book_Genre')).strip(),
            Book_Publication=str(body.get('Book_Publication')).strip() if body.get('Book_Publication') else None,
            Book_Publication_Date=pub_date,
            Book_Description=str(body.get('Book_Description')).strip() if body.get('Book_Description') else None
        )
        db.session.add(b)
        db.session.commit()
        return jsonify(b.to_dict()), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        return api_error("Database error creating book.")


@app.route("/api/v/books/<int:book_id>", methods=['GET', 'PUT', 'DELETE'])
def api_book_item(book_id):
    book = Book.query.get(book_id)
    if request.method == 'GET':
        if not book:
            return api_error("Book not found", 404)
        return jsonify(book.to_dict()), 200

    if request.method == 'PUT':
        if not book:
            return api_error("Book not found", 404)
        if not request.is_json:
            return api_error("Request body must be JSON", 415)
        body = request.get_json()
        # Update allowed fields if provided
        try:
            if 'Book_Title' in body:
                book.Book_Title = str(body['Book_Title']).strip()
            if 'Book_Author' in body:
                book.Book_Author = str(body['Book_Author']).strip()
            if 'Book_Genre' in body:
                book.Book_Genre = str(body['Book_Genre']).strip()
            if 'Book_Publication' in body:
                book.Book_Publication = str(body['Book_Publication']).strip() if body['Book_Publication'] else None
            if 'Book_Description' in body:
                book.Book_Description = str(body['Book_Description']).strip() if body['Book_Description'] else None
            if 'Book_Publication_Date' in body:
                raw = str(body['Book_Publication_Date'])
                dt = None
                for fmt in ("%Y%m%d", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw, fmt).date()
                        break
                    except Exception:
                        pass
                if not dt:
                    return api_error("Invalid Book_Publication_Date. Use yyyymmdd or YYYY-MM-DD.")
                book.Book_Publication_Date = dt

            db.session.commit()
            return jsonify(book.to_dict()), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error updating book.")

    if request.method == 'DELETE':
        if not book:
            return api_error("Book not found", 404)
        try:
            db.session.delete(book)
            db.session.commit()
            # Spec: successful request with empty response body has structure Json { }
            return jsonify({}), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error deleting book.")


# --- Genres API ---
@app.route("/api/v/genres", methods=['GET', 'POST'])
def api_genres_collection():
    if request.method == 'GET':
        limit = min(int(request.args.get('limit', DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        offset = max(int(request.args.get('offset', 0)), 0)
        q = Genre.query
        total, items = paginate_query(q.order_by(Genre.Genre_ID), limit, offset)
        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [i.to_dict() for i in items]
        }), 200

    # POST
    if not request.is_json:
        return api_error("Request body must be JSON", 415)
    body = request.get_json()
    if not body.get('Genre_Name'):
        return api_error("Missing Genre_Name")
    try:
        g = Genre(Genre_Name=str(body['Genre_Name']).strip(), Genre_Description=str(body.get('Genre_Description','')).strip() if body.get('Genre_Description') else None)
        db.session.add(g)
        db.session.commit()
        return jsonify(g.to_dict()), 201
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("Database error creating genre.")


@app.route("/api/v/genres/<int:genre_id>", methods=['GET', 'PUT', 'DELETE'])
def api_genre_item(genre_id):
    g = Genre.query.get(genre_id)
    if request.method == 'GET':
        if not g:
            return api_error("Genre not found", 404)
        return jsonify(g.to_dict()), 200

    if request.method == 'PUT':
        if not g:
            return api_error("Genre not found", 404)
        if not request.is_json:
            return api_error("Request body must be JSON", 415)
        body = request.get_json()
        try:
            if 'Genre_Name' in body:
                g.Genre_Name = str(body['Genre_Name']).strip()
            if 'Genre_Description' in body:
                g.Genre_Description = str(body.get('Genre_Description')).strip() if body.get('Genre_Description') else None
            db.session.commit()
            return jsonify(g.to_dict()), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error updating genre.")

    if request.method == 'DELETE':
        if not g:
            return api_error("Genre not found", 404)
        try:
            db.session.delete(g)
            db.session.commit()
            return jsonify({}), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error deleting genre.")


# --- Authors API ---
@app.route("/api/v/authors", methods=['GET', 'POST'])
def api_authors_collection():
    if request.method == 'GET':
        limit = min(int(request.args.get('limit', DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        offset = max(int(request.args.get('offset', 0)), 0)
        q = Author.query
        total, items = paginate_query(q.order_by(Author.Author_ID), limit, offset)
        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [i.to_dict() for i in items]
        }), 200

    if not request.is_json:
        return api_error("Request body must be JSON", 415)
    body = request.get_json()
    if not body.get('Author_Name'):
        return api_error("Missing Author_Name")
    try:
        a = Author(Author_Name=str(body['Author_Name']).strip(), Author_Bio=str(body.get('Author_Bio','')).strip() if body.get('Author_Bio') else None)
        db.session.add(a)
        db.session.commit()
        return jsonify(a.to_dict()), 201
    except SQLAlchemyError:
        db.session.rollback()
        return api_error("Database error creating author.")


@app.route("/api/v/authors/<int:author_id>", methods=['GET', 'PUT', 'DELETE'])
def api_author_item(author_id):
    a = Author.query.get(author_id)
    if request.method == 'GET':
        if not a:
            return api_error("Author not found", 404)
        return jsonify(a.to_dict()), 200

    if request.method == 'PUT':
        if not a:
            return api_error("Author not found", 404)
        if not request.is_json:
            return api_error("Request body must be JSON", 415)
        body = request.get_json()
        try:
            if 'Author_Name' in body:
                a.Author_Name = str(body['Author_Name']).strip()
            if 'Author_Bio' in body:
                a.Author_Bio = str(body.get('Author_Bio')).strip() if body.get('Author_Bio') else None
            db.session.commit()
            return jsonify(a.to_dict()), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error updating author.")

    if request.method == 'DELETE':
        if not a:
            return api_error("Author not found", 404)
        try:
            db.session.delete(a)
            db.session.commit()
            return jsonify({}), 200
        except SQLAlchemyError:
            db.session.rollback()
            return api_error("Database error deleting author.")


# -----------------------
# Error handlers (JSON format for API; HTML flash for UI)
# -----------------------
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return api_error("Not found", 404)
    return render_template_string("<h1>404 Not Found</h1><p>The requested resource was not found.</p>"), 404


@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith('/api/'):
        return api_error("Method not allowed", 405)
    return render_template_string("<h1>405 Method Not Allowed</h1>"), 405


# -----------------------
# Database init
# -----------------------
def init_db():
    if not os.path.exists(DATABASE_PATH):
        db.create_all()
        # optional: add some sample data
        sample_genres = [
            Genre(Genre_Name="Fiction", Genre_Description="Fictional works"),
            Genre(Genre_Name="Non-fiction", Genre_Description="Non-fictional works"),
        ]
        sample_authors = [
            Author(Author_Name="Jane Austen", Author_Bio="English novelist."),
            Author(Author_Name="George Orwell", Author_Bio="English novelist & essayist.")
        ]
        db.session.add_all(sample_genres + sample_authors)
        db.session.commit()


if __name__ == "__main__":
    init_db()
    # Use 0.0.0.0 only for local testing or when binding in a container; in production use a real WSGI server (gunicorn/uWSGI)
    app.run(host="0.0.0.0", port=5000, debug=True)

