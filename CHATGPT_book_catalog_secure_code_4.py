import os
from datetime import datetime, date
from dateutil.parser import parse as dateparse
from typing import Optional

from flask import (
    Flask, render_template, request, redirect, url_for, flash, get_flashed_messages,
    jsonify, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, TextAreaField, SelectField, DateField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Length, Optional as OptionalValidator, ValidationError
import bleach

# --- Config ---
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config['SECRET_KEY'] = os.environ.get('BOOKCAT_SECRET') or "dev-secret-change-me"
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(BASE_DIR, 'bookcat.db')}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Security: limit paging
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

db = SQLAlchemy(app)
csrf = CSRFProtect(app)


# --- Models ---
class Genre(db.Model):
    __tablename__ = 'genres'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True, index=True)
    description = db.Column(db.Text)

    books = db.relationship('Book', back_populates='genre', cascade="all, delete-orphan")


class Author(db.Model):
    __tablename__ = 'authors'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    bio = db.Column(db.Text)

    books = db.relationship('Book', back_populates='author', cascade="all, delete-orphan")


class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('authors.id'), nullable=False)
    genre_id = db.Column(db.Integer, db.ForeignKey('genres.id'), nullable=False)
    publication_date = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.Text)

    author = db.relationship('Author', back_populates='books')
    genre = db.relationship('Genre', back_populates='books')


# --- Forms ---
def sanitize_html(field):
    if field.data:
        # Allow a minimal set of tags in descriptions
        allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li']
        field.data = bleach.clean(field.data, tags=allowed_tags, strip=True)


class BookForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=250)])
    author_id = SelectField('Author', coerce=int, validators=[DataRequired()])
    genre_id = SelectField('Genre', coerce=int, validators=[DataRequired()])
    publication_date = DateField('Publication Date (yyyy-mm-dd)', format='%Y-%m-%d', validators=[DataRequired()])
    description = TextAreaField('Description', validators=[OptionalValidator(), Length(max=2000)])
    submit = SubmitField('Submit')

    def validate_description(form, field):
        sanitize_html(field)


class GenreForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description', validators=[OptionalValidator(), Length(max=1000)])
    submit = SubmitField('Submit')

    def validate_description(form, field):
        sanitize_html(field)


class AuthorForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=150)])
    bio = TextAreaField('Bio', validators=[OptionalValidator(), Length(max=2000)])
    submit = SubmitField('Submit')

    def validate_bio(form, field):
        sanitize_html(field)


# --- Helper utilities ---
def clamp_limit(limit: Optional[int]) -> int:
    try:
        if limit is None:
            return DEFAULT_LIMIT
        limit = int(limit)
        if limit < 1:
            return DEFAULT_LIMIT
        return min(limit, MAX_LIMIT)
    except Exception:
        return DEFAULT_LIMIT


def parse_yyyymmdd(date_str: str) -> date:
    """Parse strict yyyymmdd (or yyyymmdd with optional separators) for API queries."""
    if not date_str:
        raise ValueError("Empty date")
    # Accept either yyyymmdd or yyyy-mm-dd
    s = date_str.strip()
    # Try common formats
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    # fallback: dateutil if format unusual
    try:
        return dateparse(s).date()
    except Exception:
        raise ValueError("Invalid date format; expected yyyymmdd or YYYY-MM-DD")


def book_to_dict(book: Book):
    return {
        "id": book.id,
        "title": book.title,
        "author": {"id": book.author.id, "name": book.author.name} if book.author else None,
        "genre": {"id": book.genre.id, "name": book.genre.name} if book.genre else None,
        "publication_date": book.publication_date.strftime("%Y-%m-%d") if book.publication_date else None,
        "description": book.description or ""
    }


# --- Views / Forms pages (HTML) ---
@app.route('/')
def home():
    return render_template('home.html')


# Books list with pagination and date-range filtering
@app.route('/books')
def books_list():
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    limit = clamp_limit(request.args.get('limit'))
    offset = (page - 1) * limit

    # date filtering from form inputs (yyyy-mm-dd expected)
    after = request.args.get('after_date')
    before = request.args.get('before_date')
    query = Book.query.join(Author).join(Genre).order_by(Book.id)
    if after:
        try:
            after_d = parse_yyyymmdd(after)
            query = query.filter(Book.publication_date >= after_d)
        except ValueError:
            flash("Invalid after_date format. Use YYYYMMDD or YYYY-MM-DD.", "error")
    if before:
        try:
            before_d = parse_yyyymmdd(before)
            query = query.filter(Book.publication_date <= before_d)
        except ValueError:
            flash("Invalid before_date format. Use YYYYMMDD or YYYY-MM-DD.", "error")

    total = query.count()
    books = query.offset(offset).limit(limit).all()
    return render_template('books_list.html', books=books, page=page, limit=limit, total=total,
                           after_date=after or "", before_date=before or "")


@app.route('/books/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    return render_template('book_detail.html', book=book)


@app.route('/books/create', methods=['GET', 'POST'])
def book_create():
    form = BookForm()
    # Populate choices for author/genre
    form.author_id.choices = [(a.id, a.name) for a in Author.query.order_by(Author.name).all()]
    form.genre_id.choices = [(g.id, g.name) for g in Genre.query.order_by(Genre.name).all()]

    if form.validate_on_submit():
        # Create new book with explicit fields (avoid mass assignment)
        description = bleach.clean(form.description.data or "", tags=['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li'], strip=True)
        new_book = Book(
            title=form.title.data.strip(),
            author_id=form.author_id.data,
            genre_id=form.genre_id.data,
            publication_date=form.publication_date.data,
            description=description
        )
        db.session.add(new_book)
        db.session.commit()
        flash("Book created", "success")
        return redirect(url_for('books_list'))
    if request.method == 'POST' and not form.validate():
        flash("Please fix errors in the form", "error")
    return render_template('book_form.html', form=form, form_action=url_for('book_create'), action_label="Create")


@app.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
def book_edit(book_id):
    book = Book.query.get_or_404(book_id)
    form = BookForm(obj=book)
    form.author_id.choices = [(a.id, a.name) for a in Author.query.order_by(Author.name).all()]
    form.genre_id.choices = [(g.id, g.name) for g in Genre.query.order_by(Genre.name).all()]

    if form.validate_on_submit():
        # Update fields explicitly
        book.title = form.title.data.strip()
        book.author_id = form.author_id.data
        book.genre_id = form.genre_id.data
        book.publication_date = form.publication_date.data
        book.description = bleach.clean(form.description.data or "", tags=['b', 'i', 'u', 'em', 'strong', 'p', 'br', 'ul', 'ol', 'li'], strip=True)
        db.session.commit()
        flash("Book updated", "success")
        return redirect(url_for('books_list'))
    return render_template('book_form.html', form=form, form_action=url_for('book_edit', book_id=book_id), action_label="Update")


@app.route('/books/<int:book_id>/delete', methods=['GET', 'POST'])
def book_delete(book_id):
    book = Book.query.get_or_404(book_id)
    if request.method == 'POST':
        confirm = request.form.get('confirm')
        if confirm == 'yes':
            db.session.delete(book)
            db.session.commit()
            flash("Book deleted", "success")
            return redirect(url_for('books_list'))
        else:
            flash("Delete cancelled", "info")
            return redirect(url_for('books_list'))
    return render_template('confirm_delete.html', item=book, item_type='Book', confirm_action=url_for('book_delete', book_id=book_id))


# --- Genres (List / CRUD) ---
@app.route('/genres')
def genres_list():
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    limit = clamp_limit(request.args.get('limit'))
    offset = (page - 1) * limit
    query = Genre.query.order_by(Genre.id)
    total = query.count()
    genres = query.offset(offset).limit(limit).all()
    return render_template('genres_list.html', genres=genres, page=page, limit=limit, total=total)


@app.route('/genres/<int:genre_id>')
def genre_detail(genre_id):
    genre = Genre.query.get_or_404(genre_id)
    return render_template('genre_detail.html', genre=genre)


@app.route('/genres/create', methods=['GET', 'POST'])
def genre_create():
    form = GenreForm()
    if form.validate_on_submit():
        new = Genre(name=form.name.data.strip(), description=bleach.clean(form.description.data or "", strip=True))
        db.session.add(new)
        try:
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            flash("Error creating genre: likely duplicate name", "error")
            return render_template('genre_form.html', form=form, action_label="Create", form_action=url_for('genre_create'))
        flash("Genre created", "success")
        return redirect(url_for('genres_list'))
    return render_template('genre_form.html', form=form, form_action=url_for('genre_create'), action_label="Create")


@app.route('/genres/<int:genre_id>/edit', methods=['GET', 'POST'])
def genre_edit(genre_id):
    genre = Genre.query.get_or_404(genre_id)
    form = GenreForm(obj=genre)
    if form.validate_on_submit():
        genre.name = form.name.data.strip()
        genre.description = bleach.clean(form.description.data or "", strip=True)
        db.session.commit()
        flash("Genre updated", "success")
        return redirect(url_for('genres_list'))
    return render_template('genre_form.html', form=form, form_action=url_for('genre_edit', genre_id=genre_id), action_label="Update")


@app.route('/genres/<int:genre_id>/delete', methods=['GET', 'POST'])
def genre_delete(genre_id):
    genre = Genre.query.get_or_404(genre_id)
    if request.method == 'POST':
        confirm = request.form.get('confirm')
        if confirm == 'yes':
            # Deleting a genre will cascade delete its books (configured in models)
            db.session.delete(genre)
            db.session.commit()
            flash("Genre deleted", "success")
        else:
            flash("Delete cancelled", "info")
        return redirect(url_for('genres_list'))
    return render_template('confirm_delete.html', item=genre, item_type='Genre', confirm_action=url_for('genre_delete', genre_id=genre_id))


# --- Authors (List / CRUD) ---
@app.route('/authors')
def authors_list():
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    limit = clamp_limit(request.args.get('limit'))
    offset = (page - 1) * limit
    query = Author.query.order_by(Author.id)
    total = query.count()
    authors = query.offset(offset).limit(limit).all()
    return render_template('authors_list.html', authors=authors, page=page, limit=limit, total=total)


@app.route('/authors/<int:author_id>')
def author_detail(author_id):
    author = Author.query.get_or_404(author_id)
    return render_template('author_detail.html', author=author)


@app.route('/authors/create', methods=['GET', 'POST'])
def author_create():
    form = AuthorForm()
    if form.validate_on_submit():
        new = Author(name=form.name.data.strip(), bio=bleach.clean(form.bio.data or "", strip=True))
        db.session.add(new)
        db.session.commit()
        flash("Author created", "success")
        return redirect(url_for('authors_list'))
    return render_template('author_form.html', form=form, form_action=url_for('author_create'), action_label="Create")


@app.route('/authors/<int:author_id>/edit', methods=['GET', 'POST'])
def author_edit(author_id):
    author = Author.query.get_or_404(author_id)
    form = AuthorForm(obj=author)
    if form.validate_on_submit():
        author.name = form.name.data.strip()
        author.bio = bleach.clean(form.bio.data or "", strip=True)
        db.session.commit()
        flash("Author updated", "success")
        return redirect(url_for('authors_list'))
    return render_template('author_form.html', form=form, form_action=url_for('author_edit', author_id=author_id), action_label="Update")


@app.route('/authors/<int:author_id>/delete', methods=['GET', 'POST'])
def author_delete(author_id):
    author = Author.query.get_or_404(author_id)
    if request.method == 'POST':
        confirm = request.form.get('confirm')
        if confirm == 'yes':
            db.session.delete(author)
            db.session.commit()
            flash("Author deleted", "success")
        else:
            flash("Delete cancelled", "info")
        return redirect(url_for('authors_list'))
    return render_template('confirm_delete.html', item=author, item_type='Author', confirm_action=url_for('author_delete', author_id=author_id))


# --- API (JSON) ---
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({"message": "Not found"}), 404
    return render_template('404.html'), 404


def api_pagination_params():
    limit = clamp_limit(request.args.get('limit'))
    try:
        offset = int(request.args.get('offset', 0))
        if offset < 0:
            offset = 0
    except Exception:
        offset = 0
    return limit, offset


# Books API
@app.route('/api/v/books', methods=['GET', 'POST'])
def api_books():
    if request.method == 'GET':
        # date filters
        limit, offset = api_pagination_params()
        after = request.args.get('after_date')
        before = request.args.get('before_date')
        query = Book.query.order_by(Book.id)
        try:
            if after:
                after_d = parse_yyyymmdd(after)
                query = query.filter(Book.publication_date >= after_d)
            if before:
                before_d = parse_yyyymmdd(before)
                query = query.filter(Book.publication_date <= before_d)
        except ValueError as ex:
            return jsonify({"message": str(ex)}), 400
        total = query.count()
        books = query.offset(offset).limit(limit).all()
        return jsonify({
            "count": len(books),
            "total": total,
            "limit": limit,
            "offset": offset,
            "books": [book_to_dict(b) for b in books]
        })
    else:
        # Create new book (strict validation)
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"message": "Invalid JSON body"}), 400
        # required fields: title, author_id, genre_id, publication_date (yyyymmdd)
        title = data.get('title', '').strip()
        author_id = data.get('author_id')
        genre_id = data.get('genre_id')
        pub_raw = data.get('publication_date')
        description = data.get('description', '')

        errors = {}
        if not title:
            errors.setdefault('title', []).append('Title is required')
        if not isinstance(author_id, int):
            errors.setdefault('author_id', []).append('author_id must be integer')
        else:
            if not Author.query.get(author_id):
                errors.setdefault('author_id', []).append('author not found')
        if not isinstance(genre_id, int):
            errors.setdefault('genre_id', []).append('genre_id must be integer')
        else:
            if not Genre.query.get(genre_id):
                errors.setdefault('genre_id', []).append('genre not found')
        try:
            pub_date = parse_yyyymmdd(pub_raw)
        except Exception:
            errors.setdefault('publication_date', []).append('Invalid date format. Use yyyymmdd or YYYY-MM-DD.')

        if errors:
            return jsonify({"message": errors}), 400

        clean_desc = bleach.clean(description or "", tags=['b','i','u','em','strong','p','br','ul','ol','li'], strip=True)
        book = Book(title=title, author_id=author_id, genre_id=genre_id, publication_date=pub_date, description=clean_desc)
        db.session.add(book)
        db.session.commit()
        return jsonify(book_to_dict(book)), 201


@app.route('/api/v/books/<int:book_id>', methods=['GET', 'PUT', 'DELETE'])
def api_book_item(book_id):
    book = Book.query.get(book_id)
    if not book:
        return jsonify({"message": "Book not found"}), 404

    if request.method == 'GET':
        return jsonify(book_to_dict(book))

    if request.method == 'DELETE':
        db.session.delete(book)
        db.session.commit()
        return jsonify({}), 204

    # PUT: update
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"message": "Invalid JSON body"}), 400
    # allow partial updates, but validate types
    errors = {}
    if 'title' in data:
        if not isinstance(data['title'], str) or not data['title'].strip():
            errors.setdefault('title', []).append('Invalid title')
    if 'author_id' in data:
        if not isinstance(data['author_id'], int) or not Author.query.get(data['author_id']):
            errors.setdefault('author_id', []).append('Invalid author_id')
    if 'genre_id' in data:
        if not isinstance(data['genre_id'], int) or not Genre.query.get(data['genre_id']):
            errors.setdefault('genre_id', []).append('Invalid genre_id')
    if 'publication_date' in data:
        try:
            _ = parse_yyyymmdd(data['publication_date'])
        except Exception:
            errors.setdefault('publication_date', []).append('Invalid date format. Use yyyymmdd or YYYY-MM-DD.')

    if errors:
        return jsonify({"message": errors}), 400

    # Apply updates
    if 'title' in data:
        book.title = data['title'].strip()
    if 'author_id' in data:
        book.author_id = data['author_id']
    if 'genre_id' in data:
        book.genre_id = data['genre_id']
    if 'publication_date' in data:
        book.publication_date = parse_yyyymmdd(data['publication_date'])
    if 'description' in data:
        book.description = bleach.clean(data.get('description') or "", tags=['b','i','u','em','strong','p','br','ul','ol','li'], strip=True)

    db.session.commit()
    return jsonify(book_to_dict(book))


# Genres API
@app.route('/api/v/genres', methods=['GET', 'POST'])
def api_genres():
    if request.method == 'GET':
        limit, offset = api_pagination_params()
        q = Genre.query.order_by(Genre.id)
        total = q.count()
        items = q.offset(offset).limit(limit).all()
        return jsonify({
            "count": len(items),
            "total": total,
            "limit": limit,
            "offset": offset,
            "genres": [{"id": g.id, "name": g.name, "description": g.description or ""} for g in items]
        })
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"message": "Invalid JSON body"}), 400
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"message": {"name": ["Name is required"]}}), 400
    description = bleach.clean(data.get('description') or "", strip=True)
    new = Genre(name=name, description=description)
    db.session.add(new)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify({"message": "Genre name probably duplicate"}), 400
    return jsonify({"id": new.id, "name": new.name, "description": new.description}), 201


@app.route('/api/v/genres/<int:genre_id>', methods=['GET', 'PUT', 'DELETE'])
def api_genre_item(genre_id):
    genre = Genre.query.get(genre_id)
    if not genre:
        return jsonify({"message": "Genre not found"}), 404
    if request.method == 'GET':
        return jsonify({"id": genre.id, "name": genre.name, "description": genre.description or ""})
    if request.method == 'DELETE':
        db.session.delete(genre)
        db.session.commit()
        return jsonify({}), 204
    # PUT
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"message": "Invalid JSON body"}), 400
    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return jsonify({"message": {"name": ["Name cannot be empty"]}}), 400
        genre.name = name
    if 'description' in data:
        genre.description = bleach.clean(data.get('description') or "", strip=True)
    db.session.commit()
    return jsonify({"id": genre.id, "name": genre.name, "description": genre.description or ""})


# Authors API
@app.route('/api/v/authors', methods=['GET', 'POST'])
def api_authors():
    if request.method == 'GET':
        limit, offset = api_pagination_params()
        q = Author.query.order_by(Author.id)
        total = q.count()
        items = q.offset(offset).limit(limit).all()
        return jsonify({
            "count": len(items),
            "total": total,
            "limit": limit,
            "offset": offset,
            "authors": [{"id": a.id, "name": a.name, "bio": a.bio or ""} for a in items]
        })
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"message": "Invalid JSON body"}), 400
    name = data.get('name', '').strip()
    if not name:
        return jsonify({"message": {"name": ["Name is required"]}}), 400
    bio = bleach.clean(data.get('bio') or "", strip=True)
    new = Author(name=name, bio=bio)
    db.session.add(new)
    db.session.commit()
    return jsonify({"id": new.id, "name": new.name, "bio": new.bio}), 201


@app.route('/api/v/authors/<int:author_id>', methods=['GET', 'PUT', 'DELETE'])
def api_author_item(author_id):
    author = Author.query.get(author_id)
    if not author:
        return jsonify({"message": "Author not found"}), 404
    if request.method == 'GET':
        return jsonify({"id": author.id, "name": author.name, "bio": author.bio or ""})
    if request.method == 'DELETE':
        db.session.delete(author)
        db.session.commit()
        return jsonify({}), 204
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"message": "Invalid JSON body"}), 400
    if 'name' in data:
        name = data['name'].strip()
        if not name:
            return jsonify({"message": {"name": ["Name cannot be empty"]}}), 400
        author.name = name
    if 'bio' in data:
        author.bio = bleach.clean(data.get('bio') or "", strip=True)
    db.session.commit()
    return jsonify({"id": author.id, "name": author.name, "bio": author.bio or ""})


# --- CLI helper ---
@app.cli.command("init-db")
def init_db():
    """Initialize the database and add sample data (for dev only)."""
    db.create_all()
    if not Author.query.first():
        a1 = Author(name="Jane Austen", bio="English novelist known for realism and irony.")
        a2 = Author(name="Mark Twain", bio="American writer, humorist.")
        g1 = Genre(name="Fiction", description="Fictional works")
        g2 = Genre(name="Satire", description="Satirical works")
        db.session.add_all([a1, a2, g1, g2])
        db.session.commit()
        b1 = Book(title="Pride and Prejudice", author_id=a1.id, genre_id=g1.id, publication_date=datetime(1813,1,28).date(),
                  description="A classic novel.")
        b2 = Book(title="Adventures of Huckleberry Finn", author_id=a2.id, genre_id=g2.id, publication_date=datetime(1884,12,10).date(),
                  description="A classic American novel.")
        db.session.add_all([b1, b2])
        db.session.commit()
        print("Initialized DB with sample data.")
    else:
        print("DB already initialized.")


if __name__ == '__main__':
    app.run(debug=True)
