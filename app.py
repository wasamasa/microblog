#!/usr/bin/env python3

from datetime import datetime
from math import ceil
from pathlib import Path
from urllib.parse import urljoin

import docutils.core
import docutils.io
import docutils.nodes
from docutils.writers import html4css1
import flask
from werkzeug.contrib.atom import AtomFeed


DISPLAY_FORMAT = '%Y-%m-%d'
EXACT_FORMAT = '%Y-%m-%d %H:%M:%S'
BLOG_AUTHOR = "Vasilij Schneidermann"
BLOG_TITLE = "Emacs Horrors"
BLOG_SUBTITLE = "Rants"


app = flask.Flask(__name__)
writer = html4css1.Writer()
app.config['SERVER_NAME'] = 'emacshorrors.com'


def ensure_metadata(metadata):
    """If the metadata is well-formed, return True."""
    if 'title' in metadata and 'date' in metadata and 'category' in metadata:
        return True
    return False


@app.template_filter()
def displayed_datetime(timestamp):
    return datetime.strptime(timestamp, EXACT_FORMAT).strftime(DISPLAY_FORMAT)


@app.template_filter()
def approximate_datetime(timestamp):
    """Jinja2 filter that turns a timestamp into the approximate datetime."""
    past = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    now = datetime.now()
    delta = (now - past).total_seconds()

    times = [
        {'delta': 0, 'format': "In the future", 'factor': None},
        {'delta': 60, 'format': "Just now", 'factor': None},
        {'delta': 120, 'format': "A minute ago", 'factor': None},
        {'delta': 3600, 'format': "{} minutes ago", 'factor': 60},
        {'delta': 7200, 'format': "An hour ago", 'factor': None},
        {'delta': 86400, 'format': "{} hours ago", 'factor': 3600},
        {'delta': 172800, 'format': "A day ago", 'factor': None},
        {'delta': 604800, 'format': "{} days ago", 'factor': 86400},
        {'delta': 1209600, 'format': "A week ago", 'factor': None},
        {'delta': 2592000, 'format': "{} weeks ago", 'factor': 604800},
        {'delta': 5184000, 'format': "A month ago", 'factor': None},
        {'delta': 31104000, 'format': "{} months ago", 'factor': 2592000},
        {'delta': 62208000, 'format': "A year ago", 'factor': None}
    ]

    for time in times:
        format_string = time['format']
        factor = time['factor']
        if delta < time['delta']:
            if factor:
                return format_string.format(int(delta / factor))
            else:
                return format_string
    return "{} years ago".format(int(delta / 31104000))


def parse_post(path):
    """Parse a ReST post, return metadata and content."""
    doctree = docutils.core.publish_doctree(
        None, source_class=docutils.io.FileInput, source_path=path)
    docinfos = doctree.traverse(docutils.nodes.docinfo)
    metadata = {}
    for docinfo in docinfos:
        for child in docinfo.children:
            if child.tagname == 'field':
                tag, content = child.children
                metadata[tag.astext()] = content.astext()
            else:
                metadata[child.tagname] = child.astext()

    settings_overrides = {
        'trim_footnote_reference_space': True,
        'smart_quotes': True
    }
    content = docutils.core.publish_parts(
        None, source_class=docutils.io.FileInput,
        source_path=path, writer=writer,
        settings_overrides=settings_overrides)['body']
    return metadata, content


def parse_posts():
    """Parse all ReST posts, return a list of valid ones."""
    post_filenames = [str(p) for p in
                      (Path(__file__).resolve().parent /
                       Path('posts')).glob('*.rst')]
    posts = []
    for post_filename in post_filenames:
        slug = Path(post_filename).stem
        metadata, content = parse_post(post_filename)
        if ensure_metadata(metadata):
            post = metadata
            post['content'] = content
            post['slug'] = slug
            posts.append(post)
    return posts


def processed_posts(posts, **criteria):
    """Sort and filter posts by the given criteria."""
    filtered_posts = [post for post in posts if fits_criteria(post, criteria)]
    sorted_posts = sorted(filtered_posts, key=lambda post: post['date'])
    if 'reverse' in criteria:
        return list(reversed(sorted_posts))
    return sorted_posts


def fits_criteria(post, criteria):
    """Check whether a posts fits all criteria."""
    return all([fits_criterium(post, key, value)
                for key, value in criteria.items()])


def fits_criterium(post, key, value):
    """Check whether a posts fits a criterium defined by key and value."""
    if key == 'published' and 'published' in post and 'date' in post:
        timedelta = (datetime.now() - datetime.strptime(
            post['date'], EXACT_FORMAT)).total_seconds() > 0
        condition = post['published'] == 'yes' and timedelta
        if value:
            return condition
        else:
            return not condition
    elif key == 'category':
        return post['category'] in value
    else:
        # ignore non-existant keys
        return True


def reverse_chunks(items, pagination):
    """Pagination helper function.

    >>> reverse_chunks(list(range(1, 11)), 4)
    [[10, 9, 8, 7], [6, 5, 4, 3], [2, 1]]"""
    chunks = []
    pages = ceil(len(items) / pagination)
    if pages <= 1:
        chunks.append(reversed(items))
    else:
        start = len(items) - pagination
        end = len(items)
        for page in range(1, pages+1):
            chunks.append(list(reversed(items[start:end])))
            start = max(0, start - pagination)
            end -= pagination
    return chunks


@app.route('/categories')
def show_categories():
    """Display a list of all categories."""
    categories = all_categories()
    return flask.render_template('categories.tmpl', categories=categories)


def all_categories():
    """Return a list of all categories."""
    posts = processed_posts(parse_posts(), published=True)
    return sorted(list(set([post['category'] for post in posts])))


@app.route('/categories/<category>')
@app.route('/categories/<category>/<int:page>')
def show_category_posts(category, page=None):
    """Display a list of category posts."""
    categories = category.split(',')
    posts = category_posts(categories)
    return show_index(page=page, posts=posts)


def category_posts(categories):
    """Return list of category posts."""
    if categories:
        return processed_posts(parse_posts(), published=True,
                               reverse=True, category=categories)
    else:
        return processed_posts(parse_posts(), published=True, reverse=True)


@app.route('/')
@app.route('/posts')
@app.route('/posts/<int:page>')
def show_index(page=None, posts=None):
    """Display the appropriate paginated page.
    If the page is None, display the first page."""
    if not posts:
        posts = processed_posts(parse_posts(), published=True)
    if posts:
        pagination = 5
        if not page:
            page = 1
        pages = reverse_chunks(posts, pagination)
        if page in range(1, len(pages)+1):
            posts = pages[page-1]
            old, new = False, False
            if len(pages) > 1:
                if page != len(pages):
                    old = True
                if page != 1:
                    new = True
            return flask.render_template('posts.tmpl', posts=posts,
                                         page=page, old=old, new=new)
        else:
            return flask.render_template('error.tmpl', error="Invalid index")
    else:
        return flask.render_template('error.tmpl', error="No posts yet")


@app.route('/post/<post_slug>')
def show_post(post_slug):
    """Display a single post."""
    slug_path = (Path(__file__).resolve().parent / Path('posts') /
                 Path('{}.rst'.format(post_slug)))
    if slug_path.exists():
        metadata, content = parse_post(str(slug_path))
        if ensure_metadata(metadata):
            title = metadata['title']
            date = metadata['date']
        return flask.render_template(
            'post.tmpl', title=title, date=date, content=content)
    else:
        return flask.render_template('error.tmpl', error="No such post")


@app.route('/unpublished')
def show_unpublished():
    """Display unpaginated view of unpublished posts."""
    posts = processed_posts(parse_posts(), published=False, reverse=True)
    if posts:
        return flask.render_template('unpublished.tmpl', posts=posts)
    else:
        return flask.render_template(
            'error.tmpl', error="No unpublished posts")


@app.route('/archive')
def show_archive():
    """Display an archive of all posts."""
    posts = processed_posts(parse_posts(), published=True, reverse=True)
    if posts:
        return flask.render_template('archive.tmpl', posts=posts)
    else:
        return flask.render_template('error.tmpl', error="No posts yet")


@app.route('/feed')
@app.route('/feed/<category>')
def show_atom_feed(category=None):
    """Display an atom feed of all published posts."""
    if category:
        categories = category.split(',')
    else:
        categories = []

    posts = category_posts(categories)
    if posts:
        return atom_feed(posts)
    else:
        return flask.render_template('error.tmpl', error="No posts yet")


def atom_feed(posts):
    atom_feed = AtomFeed(
        title=BLOG_TITLE, title_type='text', author=BLOG_AUTHOR,
        subtitle=BLOG_SUBTITLE, url=flask.request.url,
        feed_url=flask.request.url_root)
    for post in posts[:10]:
        title = post['title']
        content = post['content']
        url = urljoin(flask.request.url_root, '/post/{}'.format(post['slug']))
        updated = datetime.strptime(post['date'], '%Y-%m-%d %H:%M:%S')
        published = datetime.strptime(post['date'], '%Y-%m-%d %H:%M:%S')
        atom_feed.add(
            title=title, title_type='text', content=content,
            content_type='html', url=url, updated=updated, published=published)
    return flask.Response(atom_feed.to_string(),
                          mimetype='application/atom+xml')


@app.route('/about')
def show_about():
    """Display an about page."""
    return flask.render_template('about.tmpl')


@app.route('/colophon')
def show_colophon():
    """Display an colophon page."""
    return flask.render_template('colophon.tmpl')


@app.route('/imprint')
def show_imprint():
    """Display an imprint page."""
    return flask.render_template('imprint.tmpl')


@app.route('/legal')
def show_legal():
    """Display a legal statement page."""
    return flask.render_template('legal.tmpl')

@app.route('/favicon.ico')
def show_favicon():
    return app.send_static_file('favicon.ico')


@app.errorhandler(404)
def page_not_found(error):
    """404 error handler."""
    return flask.render_template('error.tmpl', error="404 Page not found"), 404


if __name__ == '__main__':
    app.run(debug=True)