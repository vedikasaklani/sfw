import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { ArrowRight, ArrowUpRight, ArrowUpDown, Bell, BookOpen, Bookmark, BookmarkCheck, CalendarDays, CalendarPlus, Check, ChevronDown, CircleHelp, Clock3, Compass, LayoutDashboard, LibraryBig, LogOut, Minus, Moon, MoreHorizontal, Plus, RefreshCw, Search, Settings2, Sparkles, Sun, TrendingUp, X } from 'lucide-react'

const apiOrigin = new URL(window.location.origin)
apiOrigin.port = '8000'
const API = `${apiOrigin.origin}/api/v1`

type Book = {id:string; title:string; authors:string[]; subjects:string[]; year:number|null; availability:string; copies:number|null; color?:string; initials?:string; description:string; reason?:string; score?:number; added?:string; source?:string; catalogue_url?:string; items?:{item_id:number|string;library_id:string|null;item_type_id:string|null;status:string}[]}
type Loan = {id:string; book_id:string; title:string; authors:string[]; checkout_date:string; due_date:string|null; status:string}
type History = {book_id:string; title:string; date:string; subjects:string[]}
type Dashboard = {patron:{name:string;card:string;joined:string};loans:Loan[];history:History[];recommendations:Book[];analytics:{borrowed_period:number;active_loans:number;overdue:number;returned:number;subjects:{name:string;count:number}[];trend:{month:string;count:number}[]};source:string}
type MenuItem = {label:string; icon?:ReactNode; onClick:()=>void; active?:boolean}
type Trend = Dashboard['analytics']['trend']

const nav = [{id:'dashboard',label:'Overview',icon:LayoutDashboard},{id:'catalogue',label:'Explore',icon:Compass},{id:'borrowing',label:'My reading',icon:BookOpen},{id:'recommendations',label:'For you',icon:Sparkles}]
const fallback:Dashboard={patron:{name:'Library member',card:'',joined:''},loans:[],history:[],recommendations:[],analytics:{borrowed_period:0,active_loans:0,overdue:0,returned:0,subjects:[],trend:[]},source:'offline'}
const moods = ['All books','Nature','Fiction','Design','Creativity','Science']
const interestOptions = ['Nature','Design','Creativity','Fiction','Science','Technology','Arts','Psychology']
const tones = ['sage','sky','peach','lilac','butter','rose']
const DarkCtx = createContext(false)
function readTheme() { try { const t=localStorage.getItem('theme'); if(t==='dark'||t==='light') return t } catch {} return matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light' }

// Book sorts are client-side. shortcut: in Koha mode this only orders the current page, add a backend sort param if paging grows.
const bookSorts:Record<string,{label:string;fn:(a:Book,b:Book)=>number}> = {
  relevance:{label:'Best match',fn:(a,b)=>(b.score||0)-(a.score||0)},
  added:{label:'Recently added',fn:(a,b)=>(b.added||'').localeCompare(a.added||'')},
  title:{label:'Title A–Z',fn:(a,b)=>a.title.localeCompare(b.title)},
  author:{label:'Author A–Z',fn:(a,b)=>(a.authors?.[0]||'').localeCompare(b.authors?.[0]||'')},
  year:{label:'Newest published',fn:(a,b)=>(b.year||0)-(a.year||0)},
  available:{label:'Most copies',fn:(a,b)=>(b.copies??-1)-(a.copies??-1)},
}
const loanSorts:Record<string,{label:string;fn:(a:Loan,b:Loan)=>number}> = {
  due:{label:'Due soonest',fn:(a,b)=>(a.due_date||'9999').localeCompare(b.due_date||'9999')},
  recent:{label:'Recently borrowed',fn:(a,b)=>b.checkout_date.localeCompare(a.checkout_date)},
  title:{label:'Title A–Z',fn:(a,b)=>a.title.localeCompare(b.title)},
}
const historySorts:Record<string,{label:string;fn:(a:History,b:History)=>number}> = {
  recent:{label:'Most recent',fn:(a,b)=>b.date.localeCompare(a.date)},
  oldest:{label:'Oldest first',fn:(a,b)=>a.date.localeCompare(b.date)},
  title:{label:'Title A–Z',fn:(a,b)=>a.title.localeCompare(b.title)},
}
const sorted = <T,>(list:T[], sorts:Record<string,{fn:(a:T,b:T)=>number}>, key:string) => [...list].sort(sorts[key].fn)
const dayMs = 86400000
const today = () => new Date(new Date().toDateString()).getTime()
const daysUntil = (date:string|null) => !date ? Infinity : Math.round((new Date(date+'T00:00').getTime()-today())/dayMs)
const fmtDate = (date:string|null) => !date ? '—' : new Date(date+'T00:00').toLocaleDateString(undefined,{month:'short',day:'numeric'})
const initialsOf = (name:string) => name.split(/\s+/).filter(Boolean).slice(0,2).map(w=>w[0]).join('').toUpperCase()
const dueLabel = (l:Loan) => { const d=daysUntil(l.due_date); if(d===Infinity) return 'No due date'; return d<0?`${-d} day${d===-1?'':'s'} late`:d===0?'Due today':d===1?'Due tomorrow':`Due in ${d} days` }
const loanProgress = (l:Loan) => { const start=new Date(l.checkout_date+'T00:00').getTime(), end=l.due_date?new Date(l.due_date+'T00:00').getTime():start+21*dayMs; return Math.min(1,Math.max(0,(today()-start)/Math.max(dayMs,end-start))) }
const asBook = (l:Loan):Book => ({id:l.book_id,title:l.title,authors:l.authors,subjects:[],year:null,availability:'',copies:null,description:''})
const cssVars = (v:Record<string,string|number>) => v as React.CSSProperties

function readSaved():Book[] { try { return JSON.parse(localStorage.getItem('saved-books')||'[]') } catch { return [] } }
function downloadDueDates(loans:Loan[]) {
  const esc = (s:string) => s.replace(/[\\,;]/g, m => '\\'+m)
  const stamp = new Date().toISOString().replace(/[-:]/g,'').split('.')[0]+'Z'
  const events = loans.filter(l=>l.due_date).map(l => `BEGIN:VEVENT\r\nUID:${l.id}@commonplace\r\nDTSTAMP:${stamp}\r\nDTSTART;VALUE=DATE:${l.due_date!.replace(/-/g,'')}\r\nSUMMARY:${esc(`Return "${l.title}" to the library`)}\r\nEND:VEVENT`).join('\r\n')
  const a = document.createElement('a')
  a.href = URL.createObjectURL(new Blob([`BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Commonplace//Library//EN\r\n${events}\r\nEND:VCALENDAR\r\n`],{type:'text/calendar'}))
  a.download = loans.length===1 ? `due-${loans[0].title.replace(/\W+/g,'-').toLowerCase()}.ics` : 'library-due-dates.ics'
  a.click(); URL.revokeObjectURL(a.href)
}

function Menu({label,trigger,items,className='icon-btn',align='right'}:{label:string;trigger:ReactNode;items:MenuItem[];className?:string;align?:'left'|'right'}) {
  const [open,setOpen]=useState(false), ref=useRef<HTMLDivElement>(null)
  useEffect(()=>{ if(!open) return
    const outside=(e:MouseEvent)=>{ if(!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc=(e:KeyboardEvent)=>{ if(e.key==='Escape') setOpen(false) }
    document.addEventListener('mousedown',outside); document.addEventListener('keydown',esc)
    return ()=>{ document.removeEventListener('mousedown',outside); document.removeEventListener('keydown',esc) } },[open])
  return <div className="menu" ref={ref}>
    <button className={className} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={e=>{e.stopPropagation();setOpen(!open)}}>{trigger}</button>
    {open&&<div className={`menu-pop ${align}`} role="menu">{items.map(it=><button role="menuitem" key={it.label} className={it.active?'active':''} onClick={e=>{e.stopPropagation();setOpen(false);it.onClick()}}>{it.icon}<span>{it.label}</span>{it.active&&<Check size={14}/>}</button>)}</div>}
  </div>
}
function SortMenu({sorts,value,onChange}:{sorts:Record<string,{label:string}>;value:string;onChange:(k:string)=>void}) {
  return <Menu label="Sort" className="sort-btn" trigger={<><ArrowUpDown size={14}/>{sorts[value].label}<ChevronDown size={14}/></>} items={Object.entries(sorts).map(([k,s])=>({label:s.label,active:k===value,onClick:()=>onChange(k)}))}/>
}
function RangeMenu({value,onChange}:{value:number;onChange:(n:number)=>void}) {
  return <Menu label="Date range" className="sort-btn small" trigger={<><CalendarDays size={13}/>{value===3?'Last 3 months':'All months'}<ChevronDown size={13}/></>} items={[{label:'Last 3 months',active:value===3,onClick:()=>onChange(3)},{label:'All months',active:value===0,onClick:()=>onChange(0)}]}/>
}

function Cover({book,size='normal'}:{book:Book;size?:string}) {
  const colors=['#e9eedd','#dcebe0','#f6e0d3','#f3ebc8','#dbe8ef','#e7def0']
  return <div className={`cover ${size}`} style={{background:book.color||colors[(Number(book.id?.replace(/\D/g,''))||1)%colors.length]}}>
    <span className="cover-mark">{book.initials||initialsOf(book.title)}</span><span className="cover-line"/><span className="cover-title">{book.title}</span><span className="cover-author">{book.authors?.[0]}</span>
  </div>
}
function SectionHead({eyebrow,title,sub,children}:{eyebrow?:string;title:string;sub?:string;children?:ReactNode}) {
  return <div className="section-heading"><div>{eyebrow&&<div className="eyebrow">{eyebrow}</div>}<h2>{title}</h2>{sub&&<p>{sub}</p>}</div>{children&&<div className="heading-actions">{children}</div>}</div>
}

function App(){
  const [page,setPage]=useState('dashboard'),[data,setData]=useState<Dashboard>(fallback),[books,setBooks]=useState<Book[]>([]),[loading,setLoading]=useState(false)
  const [query,setQuery]=useState(''),[search,setSearch]=useState(''),[mood,setMood]=useState('All books'),[selected,setSelected]=useState<Book|null>(null)
  const [profile,setProfile]=useState({name:'Alex Morgan',email:'alex@example.test',interests:['Nature','Design','Creativity']}),[notice,setNotice]=useState('')
  const [source,setSource]=useState('offline'),[signedIn,setSignedIn]=useState(false),[loginId,setLoginId]=useState(''),[loginPassword,setLoginPassword]=useState(''),[loginBusy,setLoginBusy]=useState(false)
  const [bookSort,setBookSort]=useState('relevance'),[recSort,setRecSort]=useState('relevance'),[loanSort,setLoanSort]=useState('due'),[historySort,setHistorySort]=useState('recent'),[range,setRange]=useState(0)
  const [saved,setSaved]=useState<Book[]>(readSaved),[help,setHelp]=useState(false),[theme,setTheme]=useState(readTheme)
  const searchRef=useRef<HTMLInputElement>(null)
  const applyDashboard=(d:Dashboard)=>{setData(d);if(d.source==='demo')setSource('demo')}
  const loadDashboard=()=>fetch(`${API}/dashboard`,{credentials:'include'}).then(r=>r.ok?r.json():null).then(d=>d&&applyDashboard(d)).catch(()=>{})
  // Patron data comes from the sample library, or from Koha once a patron has signed in.
  const hasPatron=source==='demo'||(signedIn&&data.source==='koha')
  useLayoutEffect(()=>{ document.documentElement.dataset.theme=theme; try { localStorage.setItem('theme',theme) } catch {} },[theme])
  // Circular reveal from the toggle via the View Transitions API; plain swap where unsupported.
  const toggleTheme=(e:React.MouseEvent)=>{
    const next=theme==='dark'?'light':'dark', doc=document as Document&{startViewTransition?:(cb:()=>void)=>unknown}
    if(!doc.startViewTransition||matchMedia('(prefers-reduced-motion: reduce)').matches){setTheme(next);return}
    document.documentElement.style.setProperty('--tx',`${e.clientX}px`); document.documentElement.style.setProperty('--ty',`${e.clientY}px`)
    doc.startViewTransition(()=>flushSync(()=>setTheme(next)))
  }

  useEffect(()=>{fetch(`${API}/health`).then(r=>r.json()).then(async(h)=>{if(h.mode==='demo'){setSource('demo')}else{setSource('offline');try{const r=await fetch(`${API}/koha/health`);if(r.ok)setSource('koha');else setNotice(`Koha catalogue is not connected: ${(await r.json()).detail||'check backend credentials and permissions'}`)}catch{setNotice('Koha catalogue is not reachable from the portal backend.')}}const me=await fetch(`${API}/auth/me`,{credentials:'include'});setSignedIn(me.ok);if(h.mode!=='demo'&&!me.ok)return null;fetch(`${API}/profile`).then(r=>r.ok?r.json():null).then(p=>p&&setProfile({name:p.name,email:p.email,interests:p.interests}));return fetch(`${API}/dashboard`,{credentials:'include'})}).then(async r=>{if(!r)return null;if(!r.ok){const e=await r.json();throw new Error(e.detail||'Dashboard data is unavailable.')}return r.json()}).then((d:Dashboard|null)=>{if(d)applyDashboard(d)}).catch(e=>setNotice(e.message||'Can’t reach the portal API. Start the backend to load current library data.'))},[])
  useEffect(()=>{
    if(page!=='catalogue'&&page!=='recommendations') return
    if(page==='recommendations'&&!hasPatron) return
    const subject=mood==='All books'?'':`&subject=${encodeURIComponent(mood)}`
    const endpoint=page==='catalogue'?`${API}/catalogue?q=${encodeURIComponent(search)}${subject}&page=1&page_size=50`:`${API}/recommendations`
    const init:RequestInit={credentials:'include'}
    let live=true; setLoading(true)
    fetch(endpoint,init).then(async r=>{const d=await r.json();if(!r.ok)throw new Error(d.detail||'Catalogue request failed.');return d}).then(d=>live&&setBooks(d.items||[])).catch(e=>{if(live){setBooks([]);setNotice(e.message)}}).finally(()=>live&&setLoading(false))
    return ()=>{live=false}
  },[page,search,mood,hasPatron])
  // Typing in the top search updates results live while on Explore.
  useEffect(()=>{ if(page!=='catalogue') return; const t=setTimeout(()=>setSearch(query.trim()),250); return ()=>clearTimeout(t) },[query,page])
  useEffect(()=>{ try { localStorage.setItem('saved-books',JSON.stringify(saved)) } catch {} },[saved])
  useEffect(()=>{ if(!notice) return; const t=setTimeout(()=>setNotice(''),5000); return ()=>clearTimeout(t) },[notice])
  useEffect(()=>{
    const key=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){ setSelected(null); setHelp(false) }
      if(e.key==='/'&&!(e.target instanceof HTMLInputElement)){ e.preventDefault(); searchRef.current?.focus() }
    }
    document.addEventListener('keydown',key); return ()=>document.removeEventListener('keydown',key)
  },[])

  const goto=(id:string,anchor?:string)=>{setPage(id);setSelected(null);if(anchor)setTimeout(()=>document.getElementById(anchor)?.scrollIntoView({behavior:'smooth',block:'start'}),120);else window.scrollTo({top:0,behavior:'smooth'})}
  const openBook=async(book:Book)=>{setSelected(book);if(book.source==='koha'){try{const r=await fetch(`${API}/catalogue/${encodeURIComponent(book.id)}`);const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not load this record.');setSelected(d)}catch(e){setNotice(e instanceof Error?e.message:'Could not load this record.')}}}
  const openById=async(id:string)=>{try{const r=await fetch(`${API}/catalogue/${encodeURIComponent(id)}`);const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not load this record.');setSelected(d)}catch(e){setNotice(e instanceof Error?e.message:'Could not load this record.')}}
  const isSaved=(id:string)=>saved.some(b=>b.id===id)
  const toggleSave=(book:Book)=>{setSaved(s=>s.some(b=>b.id===book.id)?s.filter(b=>b.id!==book.id):[...s,book]);setNotice(isSaved(book.id)?`Removed “${book.title}” from saved.`:`Saved “${book.title}” for later.`)}
  const runSearch=()=>{setSearch(query.trim());if(page!=='catalogue')goto('catalogue')}
  const browseSubject=(s:string)=>{const m=moods.includes(s);setMood(m?s:'All books');setQuery(m?'':s);setSearch(m?'':s);goto('catalogue')}
  const refreshPicks=()=>{setLoading(true);fetch(`${API}/recommendations/refresh`,{method:'POST',credentials:'include'}).then(r=>r.json()).then(d=>{setBooks(d.items);setNotice('Your picks are refreshed.')}).catch(()=>setNotice('Could not refresh picks.')).finally(()=>setLoading(false))}

  const submitInterests=async()=>{const r=await fetch(`${API}/profile/interests`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({interests:profile.interests})});setNotice(r.ok?'Your reading interests are saved.':(await r.json()).detail)}
  const saveProfile=async()=>{const r=await fetch(`${API}/profile`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:profile.name,email:profile.email})});setNotice(r.ok?'Profile details saved.':(await r.json()).detail);if(r.ok)setData(d=>({...d,patron:{...d.patron,name:profile.name}}))}
  const signIn=async(e:React.FormEvent)=>{e.preventDefault();setLoginBusy(true);setNotice('');try{const r=await fetch(`${API}/auth/login`,{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:JSON.stringify({identifier:loginId,password:loginPassword})});const d=await r.json();if(!r.ok)throw new Error(d.detail||'Could not sign in.');setSignedIn(true);setLoginPassword('');setNotice('You are signed in with your library account.');loadDashboard()}catch(err){setNotice(err instanceof Error?err.message:'Could not sign in.')}finally{setLoginBusy(false)}}
  const signOut=async()=>{await fetch(`${API}/auth/logout`,{method:'POST',credentials:'include'});setSignedIn(false);setData(fallback);setNotice('You have signed out.')}

  const alerts=data.loans.filter(l=>daysUntil(l.due_date)<=7)
  const dueThisWeek=data.loans.filter(l=>{const d=daysUntil(l.due_date);return d>=0&&d<=7}).length
  const trend=range?data.analytics.trend.slice(-range):data.analytics.trend
  const hour=new Date().getHours(), greeting=hour<12?'Good morning':hour<18?'Good afternoon':'Good evening'
  const first=data.patron.name.split(' ')[0]
  const heads:Record<string,[string,string]>={
    dashboard:[`${greeting}, ${first}.`,'A few books chosen for you, and what’s on your shelf.'],
    catalogue:['Find your next favourite','A few good pages can take you anywhere.'],
    borrowing:['Your reading shelf','Everything you’ve borrowed, returned and saved.'],
    recommendations:['Picked with you in mind','Fresh suggestions, and a look at how you’ve been reading.'],
    account:['Your account','Make this space feel a little more like yours.'],
  }
  const loanMenu=(l:Loan):MenuItem[]=>[{label:'View book details',icon:<BookOpen size={15}/>,onClick:()=>openById(l.book_id)},{label:'Add due date to calendar',icon:<CalendarPlus size={15}/>,onClick:()=>downloadDueDates([l])}]
  const grid=(list:Book[],extra:{recommendations?:boolean;empty?:string}={})=><BookGrid books={list} openBook={openBook} isSaved={isSaved} toggleSave={toggleSave} {...extra}/>

  return <DarkCtx.Provider value={theme==='dark'}><div className="app-shell">
    <header className="topbar"><div className="topbar-inner">
      <button className="brand" onClick={()=>goto('dashboard')} aria-label="Commonplace home"><b>commonplace</b><span>✳</span></button>
      <NavPills page={page} goto={goto} loans={data.loans.length}/>
      <div className="top-actions">
        <form className="top-search" role="search" onSubmit={e=>{e.preventDefault();runSearch()}}>
          <Search size={15}/><input ref={searchRef} aria-label="Search books" placeholder="Search books…" value={query} onChange={e=>setQuery(e.target.value)}/>
          {query?<button type="button" aria-label="Clear search" onClick={()=>{setQuery('');setSearch('')}}><X size={14}/></button>:<kbd>/</kbd>}
        </form>
        <button className="icon-btn theme-btn" onClick={toggleTheme} aria-label={theme==='dark'?'Switch to light mode':'Switch to dark mode'} title={theme==='dark'?'Light mode':'Dark mode'}>{theme==='dark'?<Sun size={17}/>:<Moon size={17}/>}</button>
        <Menu label="Notifications" className={`icon-btn ${alerts.length?'notification':''}`} trigger={<><Bell size={17}/><i/></>} items={alerts.length?[...alerts.map(l=>({label:`${l.title} · ${dueLabel(l).toLowerCase()}`,icon:<Clock3 size={15}/>,onClick:()=>goto('borrowing')})),{label:'Add all due dates to calendar',icon:<CalendarPlus size={15}/>,onClick:()=>downloadDueDates(data.loans)}]:[{label:'You’re all caught up',icon:<Check size={15}/>,onClick:()=>{}}]}/>
        <Menu label="Account menu" className="avatar" trigger={initialsOf(profile.name)} items={[{label:'Account settings',icon:<Settings2 size={15}/>,onClick:()=>goto('account')},{label:'Need a little help?',icon:<CircleHelp size={15}/>,onClick:()=>setHelp(true)},...(signedIn?[{label:'Sign out',icon:<LogOut size={15}/>,onClick:signOut}]:[])]}/>
      </div>
    </div></header>

    <main className="content" key={page}>
      <div className="page-heading"><div className="eyebrow">{new Date().toLocaleDateString(undefined,{weekday:'long',month:'long',day:'numeric'})}</div><h1>{heads[page][0]}</h1><p>{heads[page][1]}</p></div>

      {page==='dashboard'&&(hasPatron?<DashboardPage data={data} trend={trend} range={range} setRange={setRange} goto={goto} openBook={openBook} openById={openById} browseSubject={browseSubject} isSaved={isSaved} toggleSave={toggleSave}/>:<CapabilityPanel title="Your patron dashboard needs a library sign-in" message="Sign in with your library account to verify your identity. Catalogue browsing remains available without signing in." action="Sign in with your library account" onAction={()=>goto('account')}/>)}

      {page==='catalogue'&&<section>
        <div className="mood-tabs" role="tablist" aria-label="Browse by mood">{moods.map((s,i)=><button role="tab" aria-selected={mood===s} className={`mood-tab ${tones[i%tones.length]} ${mood===s?'selected':''}`} key={s} onClick={()=>setMood(s)}>{s}</button>)}</div>
        <SectionHead title={search?`Results for “${search}”`:mood!=='All books'?`${mood} on the shelves`:'Fresh on the shelves'} sub={loading?'Looking through the stacks…':`${books.length} ${books.length===1?'book':'books'} to browse`}><SortMenu sorts={bookSorts} value={bookSort} onChange={setBookSort}/></SectionHead>
        {loading?<SkeletonGrid/>:grid(sorted(books,bookSorts,bookSort))}
      </section>}

      {page==='borrowing'&&hasPatron&&<>
        <div className="note-row"><Note tone="sky" label="Borrowed now" value={data.analytics.active_loans} icon={<BookOpen size={16}/>}/><Note tone="butter" label="Due this week" value={dueThisWeek} icon={<CalendarDays size={16}/>}/><Note tone="peach" label="Overdue" value={data.analytics.overdue} icon={<Clock3 size={16}/>}/></div>
        <SectionHead eyebrow="Checked out" title="On your shelf right now" sub="Each slip shows how much of the loan is left"><SortMenu sorts={loanSorts} value={loanSort} onChange={setLoanSort}/><button className="sort-btn" onClick={()=>downloadDueDates(data.loans)}><CalendarPlus size={14}/>Add all to calendar</button></SectionHead>
        <div className="slips">{sorted(data.loans,loanSorts,loanSort).map((loan,i)=>{const late=daysUntil(loan.due_date)<0;return <div className={`slip ${late?'late':''}`} key={loan.id} style={cssVars({'--i':i})}>
          <button className="slip-main" onClick={()=>openById(loan.book_id)}><Cover book={asBook(loan)} size="small"/><div className="slip-info"><b>{loan.title}</b><span>{loan.authors?.join(', ')}</span><div className="slip-bar"><i style={{width:`${loanProgress(loan)*100}%`}}/></div><small>Borrowed {fmtDate(loan.checkout_date)} · due {fmtDate(loan.due_date)}</small></div></button>
          <div className="slip-stub"><span className="stamp">{late?'Overdue':'On loan'}</span><b>{dueLabel(loan)}</b><Menu label={`Options for ${loan.title}`} trigger={<MoreHorizontal size={18}/>} items={loanMenu(loan)}/></div>
        </div>})}</div>
        <SectionHead eyebrow="Returned" title="Your reading trail" sub="The last few adventures you’ve finished"><SortMenu sorts={historySorts} value={historySort} onChange={setHistorySort}/></SectionHead>
        <ol className="trail">{sorted(data.history,historySorts,historySort).map((h,i)=><li key={h.book_id} style={cssVars({'--i':i})}><button onClick={()=>openById(h.book_id)}><span className="trail-date">{fmtDate(h.date)}</span><b>{h.title}</b><span className="trail-tags">{h.subjects.map(s=><em key={s}>{s}</em>)}</span><ArrowUpRight size={14}/></button></li>)}</ol>
      </>}
      {page==='borrowing'&&!hasPatron&&<CapabilityPanel title="Member circulation is not connected" message="This portal has no verified borrower identity yet, so it cannot show loans, due dates, or borrowing history." action="Browse the catalogue" onAction={()=>goto('catalogue')}/>}
      {page==='borrowing'&&<><SectionHead eyebrow="Bookmarked" title="Saved for later" sub="Books you bookmarked while browsing">{saved.length>0&&<SortMenu sorts={bookSorts} value={bookSort} onChange={setBookSort}/>}</SectionHead>{grid(sorted(saved,bookSorts,bookSort),{empty:'Tap the bookmark on any book to keep it here.'})}</>}

      {page==='recommendations'&&hasPatron&&<>
        <div className="pinned-note"><div><div className="eyebrow">A little serendipity <Sparkles size={13}/></div><h2>Because you’ve been exploring {profile.interests.slice(0,2).join(' & ').toLowerCase()||'new ideas'}</h2><p>Your recent reads and chosen interests give us a few clues about what you might love next.</p></div><div className="pinned-actions"><button className="btn-primary" onClick={refreshPicks}><RefreshCw size={15}/>Refresh picks</button><button className="btn-ghost" onClick={()=>goto('account')}>Tune interests</button></div></div>
        <SectionHead title="Chosen for your next chapter" sub="Thoughtful picks based on the books you’ve enjoyed"><SortMenu sorts={bookSorts} value={recSort} onChange={setRecSort}/></SectionHead>
        {loading?<SkeletonGrid/>:grid(sorted(books,bookSorts,recSort),{recommendations:true})}
        <div id="insights" className="insights-anchor"><SectionHead eyebrow="Your reading, at a glance" title="How you’ve been reading" sub="The habits behind these picks"/></div>
        <AnalyticsPage data={data} trend={trend} range={range} setRange={setRange} browseSubject={browseSubject}/>
      </>}
      {page==='recommendations'&&!hasPatron&&<CapabilityPanel title="Personal recommendations need your reading history" message="Catalogue search works independently. Recommendations appear once the portal can securely read your borrowing history." action="Browse the catalogue" onAction={()=>goto('catalogue')}/>}


      {page==='account'&&hasPatron&&<div className="account-grid">
        <div className="account-side">
          <div className="library-card"><div className="lc-top"><b>commonplace</b><span>Library card</span></div><div className="lc-name">{profile.name}</div><div className="lc-meta"><span>Card {data.patron.card}</span><span>Member since {data.patron.joined}</span></div><div className="lc-barcode" aria-hidden="true"/></div>
          <div className="panel account-panel"><h3>Your reading interests</h3><p className="muted">Pick a few. They shape your recommendations.</p><div className="interest-tags">{interestOptions.map((t,i)=><button key={t} aria-pressed={profile.interests.includes(t)} onClick={()=>setProfile({...profile,interests:profile.interests.includes(t)?profile.interests.filter(x=>x!==t):[...profile.interests,t]})} className={`${tones[i%tones.length]} ${profile.interests.includes(t)?'chosen':''}`}>{profile.interests.includes(t)&&<Check size={13}/>}{t}</button>)}</div><button className="btn-primary" onClick={submitInterests}>Save interests <Check size={15}/></button></div>
        </div>
        <form className="panel account-panel ruled" onSubmit={e=>{e.preventDefault();saveProfile()}}><h3>Your details</h3><p className="muted">Just the basics, kept in one place.</p><label>Full name<input required value={profile.name} onChange={e=>setProfile({...profile,name:e.target.value})}/></label><label>Email address<input required type="email" value={profile.email} onChange={e=>setProfile({...profile,email:e.target.value})}/></label><label>Library card number<input value={data.patron.card} disabled/></label><button className="btn-primary">Save changes <Check size={15}/></button><div className="privacy-note">Your details and interests stay with your library account.</div></form>
      </div>}
      {page==='account'&&!hasPatron&&(signedIn?<div className="panel account-panel live-account"><div className="note-icon sage"><Check size={19}/></div><h2>Your library account is signed in</h2><p>Your identity was verified by the library. Loan and profile details are not enabled in this portal yet.</p><button className="btn-primary" onClick={signOut}>Sign out</button></div>:<div className="panel account-panel live-account"><div className="note-icon butter"><CircleHelp size={19}/></div><h2>Sign in with your library account</h2><p>Use the username or library card number and password you use at the library.</p><form className="login-form" onSubmit={signIn}><label>Username or library card number<input autoComplete="username" required value={loginId} onChange={e=>setLoginId(e.target.value)} placeholder="Your library login"/></label><label>Password<input autoComplete="current-password" type="password" required value={loginPassword} onChange={e=>setLoginPassword(e.target.value)} placeholder="Your password"/></label><button className="btn-primary" disabled={loginBusy}>{loginBusy?'Signing in…':'Sign in'} <ArrowRight size={15}/></button></form><small className="login-help">If sign-in is rejected, ask the library administrator to enable <code>borrowers → api_validate_password</code> for the portal API account in Koha.</small></div>)}

      <footer><span>Made for curious minds <span className="sage-text">✳</span></span><span>Commonplace Library</span></footer>
    </main>

    {notice&&<div className="toast" role="status"><span>{notice}</span><button aria-label="Dismiss" onClick={()=>setNotice('')}><X size={15}/></button></div>}

    {selected&&<div className="modal-backdrop" onClick={()=>setSelected(null)}><div className="book-modal" role="dialog" aria-modal="true" aria-label={selected.title} onClick={e=>e.stopPropagation()}>
      <button className="modal-close" aria-label="Close" onClick={()=>setSelected(null)}><X size={19}/></button><div className="modal-cover"><Cover book={selected} size="large"/></div>
      <div className="modal-body"><div className="eyebrow">{selected.subjects?.slice(0,2).join(' · ')}</div><h2>{selected.title}</h2><p className="modal-author">by {selected.authors?.join(', ')}{selected.year?` · ${selected.year}`:''}</p><p>{selected.description||'Bibliographic details supplied by the library.'}</p>
        <div className="availability"><span className={`stamp ${selected.copies===0?'late':''}`}>{selected.copies==null?'Ask the desk':selected.copies>0?'Available':'On loan'}</span>{selected.copies!=null&&<span>{selected.copies} {selected.copies===1?'copy':'copies'} on the shelf</span>}</div>
        {(selected.items||[]).length>0&&<div className="item-list">{(selected.items||[]).map(item=><div key={item.item_id}><span>{item.library_id||'Library'}</span><span>{item.status}</span></div>)}</div>}
        <div className="modal-actions"><button className="btn-primary" onClick={()=>setNotice('Holds can’t be placed online yet. Ask at the front desk and they’ll set one aside.')}>Place a hold <ArrowRight size={15}/></button><button className="btn-ghost" onClick={()=>toggleSave(selected)}>{isSaved(selected.id)?<><BookmarkCheck size={15}/>Saved</>:<><Bookmark size={15}/>Save for later</>}</button>{selected.catalogue_url&&<a className="btn-ghost" href={selected.catalogue_url} target="_blank" rel="noopener noreferrer">Full library record <ArrowUpRight size={15}/></a>}</div>
      </div>
    </div></div>}

    {help&&<div className="modal-backdrop" onClick={()=>setHelp(false)}><div className="help-modal" role="dialog" aria-modal="true" aria-label="Help" onClick={e=>e.stopPropagation()}>
      <button className="modal-close" aria-label="Close" onClick={()=>setHelp(false)}><X size={19}/></button><h2>A little help</h2>
      <ul><li><kbd>/</kbd> jumps to the search bar from anywhere.</li><li>Pick a mood on <b>Explore</b> to filter, and use the sort menu to reorder.</li><li>The bookmark on a cover saves it to <b>My reading → Saved for later</b> on this device.</li><li>Use the <b>⋯</b> menu on a loan slip to add its due date to your calendar.</li><li><kbd>Esc</kbd> closes any open window.</li></ul>
    </div></div>}
  </div></DarkCtx.Provider>
}

function NavPills({page,goto,loans}:{page:string;goto:(id:string)=>void;loans:number}) {
  const ref=useRef<HTMLElement>(null),[pill,setPill]=useState({left:0,width:0})
  useLayoutEffect(()=>{
    const place=()=>{const el=ref.current?.querySelector<HTMLElement>('.nav-link.active');setPill(el?{left:el.offsetLeft,width:el.offsetWidth}:{left:0,width:0})}
    place(); document.fonts?.ready.then(place); window.addEventListener('resize',place); return ()=>window.removeEventListener('resize',place)
  },[page])
  return <nav className="nav-pills" ref={ref}><span className="nav-pill" style={{transform:`translateX(${pill.left}px)`,width:pill.width,opacity:pill.width?1:0}}/>
    {nav.map(item=><button key={item.id} className={`nav-link ${page===item.id?'active':''}`} aria-current={page===item.id?'page':undefined} onClick={()=>goto(item.id)}><item.icon size={15}/><span>{item.label}</span>{item.id==='borrowing'&&loans>0&&<span className="nav-count">{loans}</span>}</button>)}
  </nav>
}
function CapabilityPanel({title,message,action,onAction}:{title:string;message:string;action:string;onAction:()=>void}){return <div className="panel capability-panel"><div className="note-icon butter"><CircleHelp size={19}/></div><h2>{title}</h2><p>{message}</p><button className="btn-primary" onClick={onAction}>{action}<ArrowRight size={15}/></button></div>}
function Note({label,value,tone,icon}:{label:string;value:ReactNode;tone:string;icon:ReactNode}){return <div className={`sticky ${tone}`}><span className="note-icon">{icon}</span><b>{value}</b><span>{label}</span></div>}
function TrendChart({trend,id,height}:{trend:Trend;id:string;height:string}){
  const dark=useContext(DarkCtx), c=dark?{line:'#9fd0aa',grid:'#3a342b',tick:'#8e8473',bg:'#2a2620',border:'#3f382e',dot:'#26221d'}:{line:'#5f9270',grid:'#ece4d4',tick:'#8f877a',bg:'#fffdf7',border:'#e8dfcc',dot:'#fffcf5'}
  return <div className={height}><ResponsiveContainer width="100%" height="100%"><AreaChart data={trend} margin={{top:14,right:10,left:-24,bottom:0}}><defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={c.line} stopOpacity={.4}/><stop offset="100%" stopColor={c.line} stopOpacity={.02}/></linearGradient></defs><CartesianGrid stroke={c.grid} strokeDasharray="3 4" vertical={false}/><XAxis dataKey="month" axisLine={false} tickLine={false} tick={{fill:c.tick,fontSize:11}}/><YAxis allowDecimals={false} axisLine={false} tickLine={false} tick={{fill:c.tick,fontSize:11}}/><Tooltip cursor={{stroke:c.border}} contentStyle={{background:c.bg,border:`1px solid ${c.border}`,borderRadius:12,fontFamily:'inherit',boxShadow:'0 8px 24px -12px rgba(0,0,0,.35)'}} labelStyle={{color:c.tick}} itemStyle={{color:c.line}} formatter={(v)=>[`${v} books`,'Borrowed']}/><Area type="monotone" dataKey="count" stroke={c.line} fill={`url(#${id})`} strokeWidth={2.25} animationDuration={900} dot={{r:3,fill:c.dot,stroke:c.line,strokeWidth:2}}/></AreaChart></ResponsiveContainer></div>
}
function GoalStrip({done}:{done:number}){
  const [goal,setGoal]=useState(()=>{ try { return Math.min(52,Math.max(1,Number(localStorage.getItem('reading-goal'))||12)) } catch { return 12 } })
  useEffect(()=>{ try { localStorage.setItem('reading-goal',String(goal)) } catch {} },[goal])
  return <div className="goal taped">
    <div className="goal-copy"><div className="eyebrow">{new Date().getFullYear()} reading goal</div><h3>{Math.min(done,goal)} of {goal} books finished</h3><p className="muted">{done>=goal?'Goal reached. Lovely work, maybe stretch it a little?':`${goal-done} more to go. One spine fills in for every book you return.`}</p>
      <div className="goal-controls"><button aria-label="Lower goal" disabled={goal<=1} onClick={()=>setGoal(g=>Math.max(1,g-1))}><Minus size={15}/></button><span>{goal}</span><button aria-label="Raise goal" disabled={goal>=52} onClick={()=>setGoal(g=>Math.min(52,g+1))}><Plus size={15}/></button></div></div>
    <div className="goal-spines" aria-hidden="true">{Array.from({length:goal},(_,i)=><i key={i} className={i<done?`done ${tones[i%tones.length]}`:''} style={cssVars({'--i':i,'--h':`${62+((i*37)%34)}%`})}/>)}</div>
  </div>
}
function SubjectBars({subjects,browseSubject}:{subjects:{name:string;count:number}[];browseSubject:(s:string)=>void}){
  const max=Math.max(1,...subjects.map(s=>s.count))
  return <div className="subject-bars">{subjects.map((s,i)=><button key={s.name} className={tones[i%tones.length]} style={cssVars({'--i':i,'--w':`${(s.count/max)*100}%`})} onClick={()=>browseSubject(s.name)}><span>{s.name}</span><b>{s.count}</b><i/></button>)}</div>
}
function Shelf({children}:{children:ReactNode}){return <div className="shelf"><div className="shelf-books">{children}</div><div className="shelf-ledge"/></div>}

type DashProps={data:Dashboard;trend:Trend;range:number;setRange:(n:number)=>void;goto:(s:string,anchor?:string)=>void;openBook:(b:Book)=>void;openById:(id:string)=>void;browseSubject:(s:string)=>void;isSaved:(id:string)=>boolean;toggleSave:(b:Book)=>void}
function DashboardPage({data,trend,range,setRange,goto,openBook,openById,browseSubject,isSaved,toggleSave}:DashProps){
  const [top,...more]=data.recommendations, overdue=data.loans.filter(l=>daysUntil(l.due_date)<0).length
  return <>
    <SectionHead eyebrow="Picked for you" title="Your next good read"><button className="text-btn" onClick={()=>goto('recommendations')}>See all picks <ArrowRight size={15}/></button></SectionHead>
    {top?<div className="feature-grid">
      <article className="feature taped">
        <button className="feature-cover" onClick={()=>openBook(top)} aria-label={`Open ${top.title}`}><Cover book={top} size="large"/></button>
        <div className="feature-body"><div className="eyebrow">{top.subjects?.slice(0,2).join(' · ')}</div><h3>{top.title}</h3><p className="modal-author">by {top.authors?.join(', ')}{top.year?` · ${top.year}`:''}</p>{top.reason&&<span className="reason-note">✳ {top.reason}</span>}<p className="feature-desc">{top.description}</p>
          <div className="modal-actions"><button className="btn-primary" onClick={()=>openBook(top)}>Take a look <ArrowRight size={15}/></button><button className="btn-ghost" onClick={()=>toggleSave(top)}>{isSaved(top.id)?<><BookmarkCheck size={15}/>Saved</>:<><Bookmark size={15}/>Save</>}</button></div></div>
      </article>
      <div className="panel more-picks"><div className="eyebrow">Also for you</div>{more.map((b,i)=><button className="pick-row" key={b.id} style={cssVars({'--i':i})} onClick={()=>openBook(b)}><Cover book={b} size="small"/><div className="pick-info"><b>{b.title}</b><span>{b.authors?.[0]}</span>{b.reason&&<small>✳ {b.reason}</small>}</div><ArrowUpRight size={15}/></button>)}<button className="link-btn" onClick={()=>goto('catalogue')}>Browse the whole library <ArrowRight size={14}/></button></div>
    </div>:<div className="empty-state"><LibraryBig size={25}/><b>No picks yet</b><span>Borrow a book or two and we’ll start suggesting.</span></div>}

    <SectionHead eyebrow="Checked out" title="On your shelf" sub={`${data.loans.length} ${data.loans.length===1?'book':'books'} out${overdue?` · ${overdue} overdue`:''}`}><Menu label="Shelf options" trigger={<MoreHorizontal size={18}/>} items={[{label:'Open your reading shelf',icon:<BookOpen size={15}/>,onClick:()=>goto('borrowing')},{label:'Add due dates to calendar',icon:<CalendarPlus size={15}/>,onClick:()=>downloadDueDates(data.loans)}]}/></SectionHead>
    {data.loans.length?<Shelf>{data.loans.map((l,i)=>{const late=daysUntil(l.due_date)<0;return <button key={l.id} className="shelf-book" style={cssVars({'--i':i})} onClick={()=>openById(l.book_id)}><span className={`due-tag ${late?'late':''}`}>{dueLabel(l)}</span><Cover book={asBook(l)}/></button>})}<button className="shelf-book shelf-add" onClick={()=>goto('catalogue')}><span>+</span>Find another</button></Shelf>:<div className="empty-state"><BookOpen size={25}/><b>Nothing checked out</b><span>Your shelf is wide open.</span></div>}

    <div className="bottom-grid">
      <div className="panel"><div className="panel-heading"><div><div className="eyebrow">Reading rhythm</div><h3>{trend.reduce((n,t)=>n+t.count,0)} books borrowed</h3></div><RangeMenu value={range} onChange={setRange}/></div><TrendChart trend={trend} id="fill" height="chart-wrap"/><button className="link-btn" onClick={()=>goto('recommendations','insights')}>A closer look <ArrowRight size={14}/></button></div>
      <div className="panel"><div className="panel-heading"><div><div className="eyebrow">What you’re into</div><h3>Favourite subjects</h3></div></div><SubjectBars subjects={data.analytics.subjects.slice(0,4)} browseSubject={browseSubject}/></div>
    </div>
  </>
}
function SkeletonGrid(){return <div className="book-grid">{Array.from({length:4},(_,i)=><div className="book-card skeleton" key={i}><div className="cover"/><div className="book-details"><i/><i/><i/></div></div>)}</div>}
function BookGrid({books,openBook,isSaved,toggleSave,recommendations=false,empty='Try another search, or check back soon.'}:{books:Book[];openBook:(b:Book)=>void;isSaved:(id:string)=>boolean;toggleSave:(b:Book)=>void;recommendations?:boolean;empty?:string}){
  if(!books.length)return <div className="empty-state"><LibraryBig size={25}/><b>Nothing on this shelf just yet</b><span>{empty}</span></div>
  return <div className="book-grid">{books.map((b,i)=><article className="book-card" key={b.id} style={cssVars({'--i':i})}>
    <button className="book-open" onClick={()=>openBook(b)} aria-label={`Open ${b.title}`}><div className="cover-wrap"><Cover book={b}/>{b.copies!=null&&<span className={`stamp corner ${b.copies>0?'':'late'}`}>{b.copies>0?'In':'Out'}</span>}{i===0&&recommendations&&<span className="pick-label"><Sparkles size={11}/> Top pick</span>}</div>
      <div className="book-details"><div className="book-category">{b.subjects?.[0]||'New arrival'}</div><b>{b.title}</b><span className="author-line">{b.authors?.join(', ')}</span>{recommendations&&b.reason&&<span className="reason-note">✳ {b.reason}</span>}<div className="book-foot"><span>{b.copies==null?'Check availability':b.copies>0?`${b.copies} ${b.copies===1?'copy':'copies'} on the shelf`:'All copies on loan'}</span><ArrowUpRight size={14}/></div></div></button>
    <button className={`save-icon ${isSaved(b.id)?'saved':''}`} aria-label={isSaved(b.id)?`Remove ${b.title} from saved`:`Save ${b.title}`} aria-pressed={isSaved(b.id)} onClick={()=>toggleSave(b)}>{isSaved(b.id)?<BookmarkCheck size={15}/>:<Bookmark size={15}/>}</button>
  </article>)}</div>
}
function AnalyticsPage({data,trend,range,setRange,browseSubject}:{data:Dashboard;trend:Trend;range:number;setRange:(n:number)=>void;browseSubject:(s:string)=>void}){
  const peak=data.analytics.trend.reduce((a,b)=>b.count>a.count?b:a,{month:'—',count:0})
  return <>
    <div className="note-row four"><Note tone="sage" label="Borrowed this season" value={data.analytics.borrowed_period} icon={<BookOpen size={16}/>}/><Note tone="sky" label="On loan now" value={data.analytics.active_loans} icon={<Bookmark size={16}/>}/><Note tone="butter" label="Returned" value={data.analytics.returned} icon={<Check size={16}/>}/><Note tone="lilac" label="Busiest month" value={peak.month} icon={<TrendingUp size={16}/>}/></div>
    <div className="analytics-grid">
      <div className="panel"><div className="panel-heading"><div><div className="eyebrow">A steady little habit</div><h3>Books borrowed over time</h3></div><RangeMenu value={range} onChange={setRange}/></div><TrendChart trend={trend} id="fill2" height="chart-large"/></div>
      <div className="panel"><div className="eyebrow">Following your curiosity</div><h3>Subjects you return to</h3><p className="muted">Tap one to browse more like it.</p><SubjectBars subjects={data.analytics.subjects} browseSubject={browseSubject}/></div>
    </div>
    <GoalStrip done={data.analytics.returned}/>
    <div className="metric-note"><Sparkles size={17}/><span>These insights use your own borrowing history. They’re private to your account.</span></div>
  </>
}
export default App
