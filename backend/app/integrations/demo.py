from datetime import date, timedelta

TODAY = date.today()
BOOKS = [
 {"id":"b-101","title":"The Creative Act","authors":["Rick Rubin"],"subjects":["Creativity","Arts"],"year":2023,"isbn":"978-0-593-45098-2","availability":"Available","copies":3,"added":"2026-09-18","color":"#e7e9de","initials":"CA","description":"A generous reflection on the creative process, attention, and making work that matters."},
 {"id":"b-102","title":"Braiding Sweetgrass","authors":["Robin Wall Kimmerer"],"subjects":["Nature","Science"],"year":2013,"isbn":"978-1-57131-356-0","availability":"Available","copies":2,"added":"2026-10-04","color":"#dce6dc","initials":"BS","description":"Indigenous wisdom and botanical science meet in essays on reciprocity and the natural world."},
 {"id":"b-103","title":"Tomorrow, and Tomorrow, and Tomorrow","authors":["Gabrielle Zevin"],"subjects":["Fiction","Friendship"],"year":2022,"isbn":"978-0-593-22744-1","availability":"On loan","copies":0,"added":"2026-09-29","color":"#f1dfd4","initials":"TT","description":"A story of friendship, collaboration, and the worlds we build through games."},
 {"id":"b-104","title":"How to Do Nothing","authors":["Jenny Odell"],"subjects":["Technology","Nature"],"year":2019,"isbn":"978-1-613-53064-7","availability":"Available","copies":1,"added":"2026-10-12","color":"#e8e5cf","initials":"HN","description":"A field guide to reclaiming attention in an age of constant digital demands."},
 {"id":"b-105","title":"A Psalm for the Wild-Built","authors":["Becky Chambers"],"subjects":["Science Fiction","Nature"],"year":2021,"isbn":"978-1-250-23621-0","availability":"Available","copies":4,"added":"2026-10-20","color":"#dce5e8","initials":"PW","description":"A tea monk and a curious robot ask what people need in a hopeful, quiet novella."},
 {"id":"b-106","title":"The Design of Everyday Things","authors":["Don Norman"],"subjects":["Design","Psychology"],"year":2013,"isbn":"978-0-465-05065-9","availability":"Available","copies":2,"added":"2026-08-25","color":"#e5dfea","initials":"DE","description":"A classic exploration of how thoughtful design makes everyday objects easier to use."},
 {"id":"b-107","title":"The Overstory","authors":["Richard Powers"],"subjects":["Fiction","Nature"],"year":2018,"isbn":"978-0-393-35668-7","availability":"Available","copies":1,"added":"2026-10-09","color":"#e0e8d6","initials":"TO","description":"Interwoven lives reveal the deep connections between people and ancient trees."},
 {"id":"b-108","title":"Invisible Women","authors":["Caroline Criado Perez"],"subjects":["Society","Data"],"year":2019,"isbn":"978-1-681-77847-0","availability":"On loan","copies":0,"added":"2026-09-08","color":"#e9e0d8","initials":"IW","description":"An investigation into the consequences of a world built around male data."},
]
LOANS = [
 {"id":"l-01","book_id":"b-104","title":"How to Do Nothing","authors":["Jenny Odell"],"checkout_date":str(TODAY-timedelta(days=17)),"due_date":str(TODAY+timedelta(days=4)),"return_date":None,"status":"On track"},
 {"id":"l-02","book_id":"b-106","title":"The Design of Everyday Things","authors":["Don Norman"],"checkout_date":str(TODAY-timedelta(days=20)),"due_date":str(TODAY-timedelta(days=2)),"return_date":None,"status":"Overdue"},
]
HISTORY = [
 {"book_id":"b-101","title":"The Creative Act","date":str(TODAY-timedelta(days=32)),"subjects":["Creativity","Arts"]},
 {"book_id":"b-105","title":"A Psalm for the Wild-Built","date":str(TODAY-timedelta(days=59)),"subjects":["Science Fiction","Nature"]},
 {"book_id":"b-107","title":"The Overstory","date":str(TODAY-timedelta(days=84)),"subjects":["Fiction","Nature"]},
]


class DemoKohaClient:
    demo = True
    async def search_catalogue(self, query="", subject=None, page=1, page_size=20):
        q = query.casefold()
        filtered = [b for b in BOOKS if (not q or q in b["title"].casefold() or any(q in a.casefold() for a in b["authors"]) or any(q in s.casefold() for s in b["subjects"]) or q in b["isbn"]) and (not subject or subject in b["subjects"])]
        start = (page - 1) * page_size
        return {"items": filtered[start:start + page_size], "total": len(filtered), "page": page, "page_size": page_size}
    async def get_book(self, book_id):
        from app.integrations.koha import KohaNotFoundError
        book = next((b for b in BOOKS if b["id"] == book_id), None)
        if not book: raise KohaNotFoundError("Book not found")
        return book
    async def get_book_items(self, book_id):
        from app.integrations.koha import KohaNotFoundError
        book = next((b for b in BOOKS if b["id"] == book_id), None)
        if not book: raise KohaNotFoundError("Book not found")
        return [{"item_id": f"{book_id}-copy-{i + 1}", "library_id": "Maplewood", "item_type_id": "BOOK", "status": "Available" if book["copies"] else "On loan"} for i in range(max(1, book["copies"]))]
    async def get_current_checkouts(self, borrower_id): return LOANS
    async def get_history(self, borrower_id): return HISTORY
