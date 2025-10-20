"""
Simple single-file Flask Book Catalog application
- Uses SQLite via Flask-SQLAlchemy
- Implements Books, Genres, Authors CRUD + HTML forms + REST API (/api/v/*)
- Pagination (limit, offset), date filtering for books (yyyymmdd)
- Templates are embedded as Python multi-line strings for single-file distribution

Run:
    python3 -m venv venv
    source venv/bin/activate
    pip install flask flask_sqlalchemy
    python book_catalog.py

Open http://127.0.0.1:5000/
"""
from flask import Flask, request, render_template_string, redirect, url_for, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from urllib.parse import urlencode
import re

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///book_catalog.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'dev-key'

db = SQLAlchemy(app)

# Models
class Genre(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.Text)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'description': self.description}

class Author(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    bio = db.Column(db.Text)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'bio': self.bio}

class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('author.id'), nullable=False)
    genre_id = db.Column(db.Integer, db.ForeignKey('genre.id'), nullable=False)
    pub_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.Text)

    author = db.relationship('Author')
    genre = db.relationship('Genre')

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'author': self.author.to_dict() if self.author else None,
            'genre': self.genre.to_dict() if self.genre else None,
            'publication_date': self.pub_date.strftime('%Y-%m-%d'),
            'description': self.description
        }

# --- Utility helpers ---
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INPUT_DATE_RE = re.compile(r"^\d{8}$")  # yyyymmdd


def parse_html_date(s):
    # expects YYYY-MM-DD
    if not s:
        return None
    try:
        return datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_api_date(s):
    # expects yyyymmdd
    if not s:
        return None
    if not INPUT_DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, '%Y%m%d').date()
    except ValueError:
        return None


def paginate_query(q, default_limit=10):
    try:
        limit = int(request.args.get('limit', default_limit))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        limit = default_limit
        offset = 0
    items = q.limit(limit).offset(offset).all()
    return items, limit, offset

# --- Templates (embedded for single file) ---
base_tpl = '''
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Book Catalog</title>
  <style>
    body{font-family: Arial, Helvetica, sans-serif; margin: 20px}
    nav a{margin-right:12px}
    table{border-collapse:collapse; width:100%}
    th,td{border:1px solid #ddd;padding:8px}
    th{background:#f4f4f4}
    form.inline{display:inline}
    .error{color:red}
  </style>
</head>
<body>
<nav>
  <a href="{{ url_for('home') }}">Home</a>
  <a href="{{ url_for('books') }}">Books</a>
  <a href="{{ url_for('genres') }}">Genres</a>
  <a href="{{ url_for('authors') }}">Authors</a>
  <a href="{{ url_for('api_index') }}">API</a>
</nav>
<hr>
<div>
{{with messages = get_flashed_messages()}}
  {{if messages}}
    <ul>
    {{for m in messages}}<li>{{m}}</li>{{endfor}}
    </ul>
  {{endif}}
{{endwith}}
{{ body }}
</div>
</body>
</html>
'''

home_tpl = '''
{{extends base}}
{{block body}}
<h1>Welcome to Book Catalog</h1>
<p>This mini-app lets you manage books, authors and genres via forms and REST API.</p>
<ul>
  <li><a href="{{ url_for('books') }}">Books</a> — list, filter by publication date, create/edit/delete</li>
  <li><a href="{{ url_for('genres') }}">Genres</a></li>
  <li><a href="{{ url_for('authors') }}">Authors</a></li>
  <li><a href="{{ url_for('api_index') }}">API Reference</a></li>
</ul>
{{endblock}}
'''

books_list_tpl = '''
{{extends base}}
{{block body}}
<h1>Books</h1>
<p><a href="{{ url_for('create_book') }}">Create new</a></p>
<form method="get">
  <label>From: <input type="date" name="from" value="{{ request.args.get('from','') }}"></label>
  <label>To: <input type="date" name="to" value="{{ request.args.get('to','') }}"></label>
  <button type="submit">Refresh</button>
</form>
<table>
  <thead><tr><th>id</th><th>Title</th><th>Author</th><th>Genre</th><th>Publication date</th><th>Actions</th></tr></thead>
  <tbody>
  {{for b in books}}
    <tr>
      <td>{{ b.id }}</td>
      <td><a href="{{ url_for('book_detail', book_id=b.id) }}">{{ b.title }}</a></td>
      <td>{{ b.author.name if b.author else '' }}</td>
      <td>{{ b.genre.name if b.genre else '' }}</td>
      <td>{{ b.pub_date.strftime('%Y-%m-%d') }}</td>
      <td>
        <a href="{{ url_for('edit_book', book_id=b.id) }}">Update</a>
        <form class="inline" method="post" action="{{ url_for('delete_book', book_id=b.id) }}" onsubmit="return confirm('Delete this book?');">
          <button type="submit">Delete</button>
        </form>
      </td>
    </tr>
  {{endfor}}
  </tbody>
</table>
<div style="margin-top:10px">
  <a href="{{ paging_prev }}">Previous</a> | <a href="{{ paging_next }}">Next</a>
</div>
{{endblock}}
'''

book_detail_tpl = '''
{{extends base}}
{{block body}}
<h1>Book details</h1>
<table>
  <tr><th>id</th><td>{{ book.id }}</td></tr>
  <tr><th>Title</th><td>{{ book.title }}</td></tr>
  <tr><th>Author</th><td><a href="{{ url_for('author_detail', author_id=book.author.id) }}">{{ book.author.name }}</a></td></tr>
  <tr><th>Genre</th><td><a href="{{ url_for('genre_detail', genre_id=book.genre.id) }}">{{ book.genre.name }}</a></td></tr>
  <tr><th>Description</th><td>{{ book.description }}</td></tr>
  <tr><th>Publication date</th><td>{{ book.pub_date.strftime('%Y-%m-%d') }}</td></tr>
</table>
<p><a href="{{ url_for('edit_book', book_id=book.id) }}">Update</a></p>
{{endblock}}
'''

book_form_tpl = '''
{{extends base}}
{{block body}}
<h1>{{ 'Edit' if book else 'Create new' }} Book</h1>
{{if errors}}
  <div class="error">{{ errors|join('<br>')|safe }}</div>
{{endif}}
<form method="post">
  <label>Title<br><input name="title" value="{{ request.form.get('title', book.title if book else '') }}"></label><br>
  <label>Author<br>
    <select name="author_id">
      <option value="">-- choose --</option>
      {{for a in authors}}
        <option value="{{ a.id }}" {{if (request.form.get('author_id')|int == a.id) or (book and book.author_id==a.id and not request.form.get('author_id'))}}selected{{endif}}>{{ a.name }}</option>
      {{endfor}}
    </select>
  </label><br>
  <label>Genre<br>
    <select name="genre_id">
      <option value="">-- choose --</option>
      {{for g in genres}}
        <option value="{{ g.id }}" {{if (request.form.get('genre_id')|int == g.id) or (book and book.genre_id==g.id and not request.form.get('genre_id'))}}selected{{endif}}>{{ g.name }}</option>
      {{endfor}}
    </select>
  </label><br>
  <label>Description<br><textarea name="description">{{ request.form.get('description', book.description if book else '') }}</textarea></label><br>
  <label>Publication date<br><input type="date" name="pub_date" value="{{ request.form.get('pub_date', book.pub_date.strftime('%Y-%m-%d') if book else '') }}"></label><br>
  <button type="submit">Submit</button>
  <a href="{{ url_for('books') }}"><button type="button">Cancel</button></a>
</form>
{{endblock}}
'''

list_entities_tpl = '''
{{extends base}}
{{block body}}
<h1>{{ title }}</h1>
<p><a href="{{ create_url }}">Create new</a></p>
<table>
  <thead><tr>{{for c in columns}}<th>{{ c }}</th>{{endfor}}<th>Actions</th></tr></thead>
  <tbody>
  {{for it in items}}
    <tr>
      {{for key in keys}}
        <td>{{ getattr(it, key) }}</td>
      {{endfor}}
      <td>
        <a href="{{ url_for(detail_endpoint, **{id_name: it.id}) }}">View</a>
        <a href="{{ url_for(edit_endpoint, **{id_name: it.id}) }}">Update</a>
        <form class="inline" method="post" action="{{ url_for(delete_endpoint, **{id_name: it.id}) }}" onsubmit="return confirm('Delete?');">
          <button type="submit">Delete</button>
        </form>
      </td>
    </tr>
  {{endfor}}
  </tbody>
</table>
<div style="margin-top:10px">
  <a href="{{ paging_prev }}">Previous</a> | <a href="{{ paging_next }}">Next</a>
</div>
{{endblock}}
'''

entity_detail_tpl = '''
{{extends base}}
{{block body}}
<h1>{{ title }}</h1>
<table>
  {{for k,v in fields.items()}}
    <tr><th>{{ k }}</th><td>{{ v }}</td></tr>
  {{endfor}}
</table>
<p><a href="{{ list_url }}">Back to list</a></p>
{{endblock}}
'''

api_index_tpl = '''
{{extends base}}
{{block body}}
<h1>API</h1>
<p>Available endpoints:</p>
<ul>
  <li>Books: GET /api/v/books, GET /api/v/books/&lt;id&gt;, POST /api/v/books, PUT /api/v/books/&lt;id&gt;, DELETE /api/v/books/&lt;id&gt;</li>
  <li>Books date filters: ?after_date=yyyymmdd&amp;before_date=yyyymmdd</li>
  <li>Genres: /api/v/genres</li>
  <li>Authors: /api/v/authors</li>
</ul>
{{endblock}}
'''

# --- Routes for forms ---
@app.route('/')
def home():
    return render_template_string(home_tpl, base=base_tpl)

# Books list with date filtering and pagination
@app.route('/books')
def books():
    q = Book.query.order_by(Book.id)
    # date filters from HTML (YYYY-MM-DD)
    from_s = request.args.get('from')
    to_s = request.args.get('to')
    if from_s:
        d = parse_html_date(from_s)
        if d:
            q = q.filter(Book.pub_date >= d)
    if to_s:
        d = parse_html_date(to_s)
        if d:
            q = q.filter(Book.pub_date <= d)
    # pagination via limit/offset
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        limit = 10; offset = 0
    books_list = q.limit(limit).offset(offset).all()
    # build paging URLs preserving querystring
    base_args = {k: v for k, v in request.args.items() if k not in ('offset',)}
    prev_args = dict(base_args)
    prev_args['offset'] = max(0, offset - limit)
    next_args = dict(base_args)
    next_args['offset'] = offset + limit
    paging_prev = url_for('books') + '?' + urlencode(prev_args)
    paging_next = url_for('books') + '?' + urlencode(next_args)
    return render_template_string(books_list_tpl, base=base_tpl, books=books_list, request=request, paging_prev=paging_prev, paging_next=paging_next)

@app.route('/books/<int:book_id>')
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    return render_template_string(book_detail_tpl, base=base_tpl, book=book)

@app.route('/books/create', methods=['GET','POST'])
def create_book():
    authors = Author.query.order_by(Author.name).all()
    genres = Genre.query.order_by(Genre.name).all()
    errors = []
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        author_id = request.form.get('author_id')
        genre_id = request.form.get('genre_id')
        description = request.form.get('description','').strip()
        pub_date = parse_html_date(request.form.get('pub_date',''))
        if not title:
            errors.append('Title is required')
        if not author_id or not Author.query.get(author_id):
            errors.append('Valid author is required')
        if not genre_id or not Genre.query.get(genre_id):
            errors.append('Valid genre is required')
        if not pub_date:
            errors.append('Valid publication date is required')
        if not errors:
            b = Book(title=title, author_id=int(author_id), genre_id=int(genre_id), description=description, pub_date=pub_date)
            db.session.add(b)
            db.session.commit()
            return redirect(url_for('books'))
    return render_template_string(book_form_tpl, base=base_tpl, book=None, authors=authors, genres=genres, errors=errors, request=request)

@app.route('/books/<int:book_id>/edit', methods=['GET','POST'])
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    authors = Author.query.order_by(Author.name).all()
    genres = Genre.query.order_by(Genre.name).all()
    errors = []
    if request.method == 'POST':
        title = request.form.get('title','').strip()
        author_id = request.form.get('author_id')
        genre_id = request.form.get('genre_id')
        description = request.form.get('description','').strip()
        pub_date = parse_html_date(request.form.get('pub_date',''))
        if not title:
            errors.append('Title is required')
        if not author_id or not Author.query.get(author_id):
            errors.append('Valid author is required')
        if not genre_id or not Genre.query.get(genre_id):
            errors.append('Valid genre is required')
        if not pub_date:
            errors.append('Valid publication date is required')
        if not errors:
            book.title = title
            book.author_id = int(author_id)
            book.genre_id = int(genre_id)
            book.description = description
            book.pub_date = pub_date
            db.session.commit()
            return redirect(url_for('books'))
    return render_template_string(book_form_tpl, base=base_tpl, book=book, authors=authors, genres=genres, errors=errors, request=request)

@app.route('/books/<int:book_id>/delete', methods=['POST'])
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    db.session.delete(book)
    db.session.commit()
    return redirect(url_for('books'))

# --- Genres and Authors: list/detail/create/edit/delete ---
@app.route('/genres')
def genres():
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        limit = 10; offset = 0
    items = Genre.query.order_by(Genre.id).limit(limit).offset(offset).all()
    prev = url_for('genres') + '?' + urlencode({'offset': max(0, offset-limit), 'limit': limit})
    next_ = url_for('genres') + '?' + urlencode({'offset': offset+limit, 'limit': limit})
    return render_template_string(list_entities_tpl, base=base_tpl, title='Genres', items=items, columns=['id','Name','Description'], keys=['id','name','description'], detail_endpoint='genre_detail', edit_endpoint='edit_genre', delete_endpoint='delete_genre', create_url=url_for('create_genre'), id_name='genre_id', paging_prev=prev, paging_next=next_)

@app.route('/genres/<int:genre_id>')
def genre_detail(genre_id):
    g = Genre.query.get_or_404(genre_id)
    fields = {'id': g.id, 'Name': g.name, 'Description': g.description}
    return render_template_string(entity_detail_tpl, base=base_tpl, title='Genre details', fields=fields, list_url=url_for('genres'))

@app.route('/genres/create', methods=['GET','POST'])
def create_genre():
    errors = []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        description = request.form.get('description','').strip()
        if not name:
            errors.append('Name required')
        if Genre.query.filter_by(name=name).first():
            errors.append('Genre with that name already exists')
        if not errors:
            g = Genre(name=name, description=description)
            db.session.add(g)
            db.session.commit()
            return redirect(url_for('genres'))
    # reuse simple form built inline
    form = '''<h1>Create new Genre</h1>
<form method="post">
  <label>Name<br><input name="name" value="%s"></label><br>
  <label>Description<br><textarea name="description">%s</textarea></label><br>
  <button type="submit">Submit</button>
  <a href="%s"><button type="button">Cancel</button></a>
</form>''' % (request.form.get('name',''), request.form.get('description',''), url_for('genres'))
    if errors:
        form = '<div class="error">%s</div>'%('<br>'.join(errors)) + form
    return render_template_string(base_tpl, body=form)

@app.route('/genres/<int:genre_id>/edit', methods=['GET','POST'])
def edit_genre(genre_id):
    g = Genre.query.get_or_404(genre_id)
    errors = []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        description = request.form.get('description','').strip()
        if not name:
            errors.append('Name required')
        if not errors:
            g.name = name
            g.description = description
            db.session.commit()
            return redirect(url_for('genres'))
    form = '''<h1>Edit Genre</h1>
<form method="post">
  <label>Name<br><input name="name" value="%s"></label><br>
  <label>Description<br><textarea name="description">%s</textarea></label><br>
  <button type="submit">Submit</button>
  <a href="%s"><button type="button">Cancel</button></a>
</form>''' % (request.form.get('name', g.name), request.form.get('description', g.description), url_for('genres'))
    if errors:
        form = '<div class="error">%s</div>'%('<br>'.join(errors)) + form
    return render_template_string(base_tpl, body=form)

@app.route('/genres/<int:genre_id>/delete', methods=['POST'])
def delete_genre(genre_id):
    g = Genre.query.get_or_404(genre_id)
    db.session.delete(g)
    db.session.commit()
    return redirect(url_for('genres'))

# Authors
@app.route('/authors')
def authors():
    try:
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
    except ValueError:
        limit = 10; offset = 0
    items = Author.query.order_by(Author.id).limit(limit).offset(offset).all()
    prev = url_for('authors') + '?' + urlencode({'offset': max(0, offset-limit), 'limit': limit})
    next_ = url_for('authors') + '?' + urlencode({'offset': offset+limit, 'limit': limit})
    return render_template_string(list_entities_tpl, base=base_tpl, title='Authors', items=items, columns=['id','Name','Bio'], keys=['id','name','bio'], detail_endpoint='author_detail', edit_endpoint='edit_author', delete_endpoint='delete_author', create_url=url_for('create_author'), id_name='author_id', paging_prev=prev, paging_next=next_)

@app.route('/authors/<int:author_id>')
def author_detail(author_id):
    a = Author.query.get_or_404(author_id)
    fields = {'id': a.id, 'Name': a.name, 'Bio': a.bio}
    return render_template_string(entity_detail_tpl, base=base_tpl, title='Author details', fields=fields, list_url=url_for('authors'))

@app.route('/authors/create', methods=['GET','POST'])
def create_author():
    errors = []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        bio = request.form.get('bio','').strip()
        if not name:
            errors.append('Name required')
        if Author.query.filter_by(name=name).first():
            errors.append('Author with that name already exists')
        if not errors:
            a = Author(name=name, bio=bio)
            db.session.add(a)
            db.session.commit()
            return redirect(url_for('authors'))
    form = '''<h1>Create new Author</h1>
<form method="post">
  <label>Name<br><input name="name" value="%s"></label><br>
  <label>Bio<br><textarea name="bio">%s</textarea></label><br>
  <button type="submit">Submit</button>
  <a href="%s"><button type="button">Cancel</button></a>
</form>''' % (request.form.get('name',''), request.form.get('bio',''), url_for('authors'))
    if errors:
        form = '<div class="error">%s</div>'%('<br>'.join(errors)) + form
    return render_template_string(base_tpl, body=form)

@app.route('/authors/<int:author_id>/edit', methods=['GET','POST'])
def edit_author(author_id):
    a = Author.query.get_or_404(author_id)
    errors = []
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        bio = request.form.get('bio','').strip()
        if not name:
            errors.append('Name required')
        if not errors:
            a.name = name
            a.bio = bio
            db.session.commit()
            return redirect(url_for('authors'))
    form = '''<h1>Edit Author</h1>
<form method="post">
  <label>Name<br><input name="name" value="%s"></label><br>
  <label>Bio<br><textarea name="bio">%s</textarea></label><br>
  <button type="submit">Submit</button>
  <a href="%s"><button type="button">Cancel</button></a>
</form>''' % (request.form.get('name', a.name), request.form.get('bio', a.bio), url_for('authors'))
    if errors:
        form = '<div class="error">%s</div>'%('<br>'.join(errors)) + form
    return render_template_string(base_tpl, body=form)

@app.route('/authors/<int:author_id>/delete', methods=['POST'])
def delete_author(author_id):
    a = Author.query.get_or_404(author_id)
    db.session.delete(a)
    db.session.commit()
    return redirect(url_for('authors'))

# --- API ---
@app.route('/api/v/books', methods=['GET','POST'])
def api_books():
    if request.method == 'GET':
        # date filters: after_date and before_date in yyyymmdd
        after = parse_api_date(request.args.get('after_date'))
        before = parse_api_date(request.args.get('before_date'))
        q = Book.query
        if after:
            q = q.filter(Book.pub_date >= after)
        if before:
            q = q.filter(Book.pub_date <= before)
        try:
            limit = int(request.args.get('limit', 10))
            offset = int(request.args.get('offset', 0))
        except ValueError:
            limit = 10; offset = 0
        items = q.order_by(Book.id).limit(limit).offset(offset).all()
        return jsonify([b.to_dict() for b in items])
    else:
        # create new book
        data = request.get_json() or {}
        # expected fields: title, author_id, genre_id, publication_date (yyyymmdd) or (YYYY-MM-DD)
        title = data.get('title','').strip()
        author_id = data.get('author_id')
        genre_id = data.get('genre_id')
        pub = data.get('publication_date')
        pub_date = parse_api_date(pub) or parse_html_date(pub)
        description = data.get('description','')
        errors = []
        if not title:
            errors.append('Title is required')
        if not author_id or not Author.query.get(author_id):
            errors.append('Valid author_id is required')
        if not genre_id or not Genre.query.get(genre_id):
            errors.append('Valid genre_id is required')
        if not pub_date:
            errors.append('Valid publication_date is required (yyyymmdd or YYYY-MM-DD)')
        if errors:
            return jsonify({'message': {'error': errors}}), 400
        b = Book(title=title, author_id=int(author_id), genre_id=int(genre_id), pub_date=pub_date, description=description)
        db.session.add(b)
        db.session.commit()
        return jsonify(b.to_dict()), 201

@app.route('/api/v/books/<int:book_id>', methods=['GET','PUT','DELETE'])
def api_book(book_id):
    b = Book.query.get(book_id)
    if not b:
        return jsonify({'message': 'Book not found'}), 404
    if request.method == 'GET':
        return jsonify(b.to_dict())
    elif request.method == 'DELETE':
        db.session.delete(b)
        db.session.commit()
        return ('', 204)
    else:
        data = request.get_json() or {}
        title = data.get('title')
        author_id = data.get('author_id')
        genre_id = data.get('genre_id')
        pub = data.get('publication_date')
        pub_date = parse_api_date(pub) or parse_html_date(pub)
        description = data.get('description')
        errors = []
        if title is not None and not title.strip():
            errors.append('Title cannot be empty')
        if author_id is not None and not Author.query.get(author_id):
            errors.append('Valid author_id required')
        if genre_id is not None and not Genre.query.get(genre_id):
            errors.append('Valid genre_id required')
        if pub is not None and not pub_date:
            errors.append('publication_date must be yyyymmdd or YYYY-MM-DD')
        if errors:
            return jsonify({'message': {'error': errors}}), 400
        if title is not None:
            b.title = title
        if author_id is not None:
            b.author_id = int(author_id)
        if genre_id is not None:
            b.genre_id = int(genre_id)
        if pub_date is not None:
            b.pub_date = pub_date
        if description is not None:
            b.description = description
        db.session.commit()
        return jsonify(b.to_dict())

# Genres API
@app.route('/api/v/genres', methods=['GET','POST'])
def api_genres():
    if request.method == 'GET':
        try:
            limit = int(request.args.get('limit', 10))
            offset = int(request.args.get('offset', 0))
        except ValueError:
            limit = 10; offset = 0
        items = Genre.query.order_by(Genre.id).limit(limit).offset(offset).all()
        return jsonify([g.to_dict() for g in items])
    else:
        data = request.get_json() or {}
        name = data.get('name','').strip()
        desc = data.get('description','')
        if not name:
            return jsonify({'message': 'Name required'}), 400
        if Genre.query.filter_by(name=name).first():
            return jsonify({'message': 'Genre already exists'}), 400
        g = Genre(name=name, description=desc)
        db.session.add(g)
        db.session.commit()
        return jsonify(g.to_dict()), 201

@app.route('/api/v/genres/<int:genre_id>', methods=['GET','PUT','DELETE'])
def api_genre(genre_id):
    g = Genre.query.get(genre_id)
    if not g:
        return jsonify({'message':'Genre not found'}), 404
    if request.method == 'GET':
        return jsonify(g.to_dict())
    elif request.method == 'DELETE':
        db.session.delete(g)
        db.session.commit()
        return ('', 204)
    else:
        data = request.get_json() or {}
        name = data.get('name')
        desc = data.get('description')
        if name is not None:
            if not name.strip():
                return jsonify({'message':'Name cannot be empty'}), 400
            g.name = name
        if desc is not None:
            g.description = desc
        db.session.commit()
        return jsonify(g.to_dict())

# Authors API
@app.route('/api/v/authors', methods=['GET','POST'])
def api_authors():
    if request.method == 'GET':
        try:
            limit = int(request.args.get('limit', 10))
            offset = int(request.args.get('offset', 0))
        except ValueError:
            limit = 10; offset = 0
        items = Author.query.order_by(Author.id).limit(limit).offset(offset).all()
        return jsonify([a.to_dict() for a in items])
    else:
        data = request.get_json() or {}
        name = data.get('name','').strip()
        bio = data.get('bio','')
        if not name:
            return jsonify({'message': 'Name required'}), 400
        if Author.query.filter_by(name=name).first():
            return jsonify({'message': 'Author already exists'}), 400
        a = Author(name=name, bio=bio)
        db.session.add(a)
        db.session.commit()
        return jsonify(a.to_dict()), 201

@app.route('/api/v/authors/<int:author_id>', methods=['GET','PUT','DELETE'])
def api_author(author_id):
    a = Author.query.get(author_id)
    if not a:
        return jsonify({'message':'Author not found'}), 404
    if request.method == 'GET':
        return jsonify(a.to_dict())
    elif request.method == 'DELETE':
        db.session.delete(a)
        db.session.commit()
        return ('', 204)
    else:
        data = request.get_json() or {}
        name = data.get('name')
        bio = data.get('bio')
        if name is not None:
            if not name.strip():
                return jsonify({'message':'Name cannot be empty'}), 400
            a.name = name
        if bio is not None:
            a.bio = bio
        db.session.commit()
        return jsonify(a.to_dict())

@app.route('/api')
def api_index():
    return render_template_string(api_index_tpl, base=base_tpl)

# --- DB init + sample data ---
@app.cli.command('initdb')
def initdb_command():
    """Initialize the database."""
    db.drop_all()
    db.create_all()
    # seed some sample data
    g1 = Genre(name='Fantasy', description='Fantasy books')
    g2 = Genre(name='Science Fiction', description='Sci-Fi')
    a1 = Author(name='J. R. R. Tolkien', bio='Author of LOTR')
    a2 = Author(name='Isaac Asimov', bio='Sci-Fi author')
    db.session.add_all([g1,g2,a1,a2])
    db.session.commit()
    b1 = Book(title='The Hobbit', author_id=a1.id, genre_id=g1.id, pub_date=datetime(1937,9,21).date(), description='Bilbo\'s adventure')
    b2 = Book(title='Foundation', author_id=a2.id, genre_id=g2.id, pub_date=datetime(1951,6,1).date(), description='Foundation series')
    db.session.add_all([b1,b2])
    db.session.commit()
    print('Initialized the database and added sample data.')

if __name__ == '__main__':
    # create DB automatically if not exists
    with app.app_context():
        db.create_all()
    app.run(debug=True)

