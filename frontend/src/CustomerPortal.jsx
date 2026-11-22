import React, { useEffect, useMemo, useState } from "react";

const STORAGE = {
  bookings: "travelintel-demo-bookings-v1",
  email: "travelintel-demo-customer-email",
  wishlist: "travelintel-wishlist-v1",
  trips: "travelintel-saved-trips-v1",
  preferences: "travelintel-preferences-v1",
};

const PHOTO_IDS = [
  "photo-1501785888041-af3ef285b470",
  "photo-1464822759023-fed622ff2c3b",
  "photo-1519046904884-53103b34b206",
  "photo-1507525428034-b723cf961d3e",
  "photo-1470770841072-f978cf4d019e",
  "photo-1530789253388-582c481c54b0",
];
const MOODS = [
  { id: "Adventure", icon: "↗", text: "Bold routes and active days" },
  { id: "Relaxation", icon: "≈", text: "Slow down and recharge" },
  { id: "Romance", icon: "♡", text: "A getaway for two" },
  { id: "Nature", icon: "⌁", text: "Landscapes and the outdoors" },
  { id: "Family Vacation", icon: "⌂", text: "Made for a family trip" },
  { id: "Spiritual", icon: "✧", text: "Heritage and reflection" },
  { id: "Beach Escape", icon: "☼", text: "Coastal time and sea air" },
  { id: "Budget Escape", icon: "↘", text: "Start with a lower-cost range" },
];
const WEATHER_CITIES = ["bengaluru", "bombay", "delhi", "hyderabad", "jaipur", "kanpur", "nagpur", "pune"];

async function getJson(url, options) {
  const response = await fetch(url, options);
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`The TravelIntel API returned an invalid response (${response.status}).`);
  }
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status}).`);
  return payload;
}

function readStorage(key, fallback) {
  try {
    const saved = window.localStorage.getItem(key);
    return saved ? JSON.parse(saved) : fallback;
  } catch (error) {
    if (error instanceof SyntaxError) return fallback;
    throw error;
  }
}

function writeStorage(key, value) {
  window.localStorage.setItem(key, JSON.stringify(value));
}

function number(value, digits = 0) {
  if (value === null || value === undefined || value === "") return "Not in source data";
  const parsed = Number(value);
  return Number.isFinite(parsed)
    ? parsed.toLocaleString(undefined, { maximumFractionDigits: digits })
    : String(value);
}

function nightCount(checkIn, checkOut) {
  if (!checkIn || !checkOut || checkOut <= checkIn) return 0;
  const start = Date.parse(`${checkIn}T00:00:00Z`);
  const end = Date.parse(`${checkOut}T00:00:00Z`);
  return Number.isFinite(start) && Number.isFinite(end) ? (end - start) / 86400000 : 0;
}

function historicalStayTotal(price, nights, rooms) {
  if (!price || nights < 1 || rooms < 1) return null;
  const amount = Number(String(price).replace(/,/g, "").replace(/[^\d.-]/g, ""));
  if (!Number.isFinite(amount)) return null;
  const symbol = String(price).replace(/[\d,.\s-]/g, "");
  const total = (amount * nights * rooms).toLocaleString(undefined, { maximumFractionDigits: 2 });
  return `${symbol}${total}`;
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function historicalPriceValue(value) {
  const parsed = Number(String(value ?? "").replace(/,/g, "").replace(/[^\d.-]/g, ""));
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function createRequestId() {
  return window.crypto?.randomUUID?.() || `req-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalize(value) {
  return String(value ?? "").toLowerCase().replace(/[_-]+/g, " ").trim();
}

function isMoodMatch(destination, mood) {
  const types = list(destination.trip_types).map(normalize);
  const idealFor = list(destination.ideal_for).map(normalize);
  const words = {
    Adventure: ["adventure", "trekking"],
    Relaxation: ["wellness", "relaxation"],
    Romance: ["couple", "romance", "honeymoon"],
    Nature: ["nature", "wildlife", "trekking"],
    "Family Vacation": ["family", "family with kids", "family with elderly"],
    Spiritual: ["spiritual", "religious", "pilgrimage", "pilgrim"],
    "Beach Escape": ["beach", "coastal"],
    "Budget Escape": [],
  }[mood] ?? [];
  if (mood === "Budget Escape") return Boolean(destination.budgets?.budget?.length);
  return types.some((type) => words.includes(type) || words.some((word) => type.includes(word))) ||
    idealFor.some((type) => words.includes(type) || words.some((word) => type.includes(word)));
}

function moodReason(destination, mood) {
  if (mood === "Budget Escape") return "A source-provided budget range is available for this destination.";
  const matched = [...list(destination.trip_types), ...list(destination.ideal_for)]
    .find((value) => {
      const selected = normalize(value);
      const words = {
        Adventure: ["adventure", "trekking"], Relaxation: ["wellness", "relaxation"],
        Romance: ["couple", "romance", "honeymoon"], Nature: ["nature", "wildlife", "trekking"],
        "Family Vacation": ["family"], Spiritual: ["spiritual", "religious", "pilgrimage", "pilgrim"],
        "Beach Escape": ["beach", "coastal"],
      }[mood] ?? [];
      return words.some((word) => selected.includes(word));
    });
  return matched ? `The destination dataset lists “${matched.replaceAll("_", " ")}”.` : "A matching destination category is present in the source.";
}

function formatBudget(range) {
  if (!Array.isArray(range) || range.length < 2) return "Budget estimate not available";
  return `${number(range[0])}–${number(range[1])} per day · source currency unspecified`;
}

function getPhotoUrl(index) {
  const photo = PHOTO_IDS[Math.abs(index) % PHOTO_IDS.length];
  return `https://images.unsplash.com/${photo}?auto=format&fit=crop&w=960&q=75`;
}

function Photo({ src, alt, index, className = "" }) {
  const [failed, setFailed] = useState(false);
  const image = src || getPhotoUrl(index);
  return (
    <div className={`customer-photo ${failed ? "photo-failed" : ""} ${className}`}>
      {!failed ? <img src={image} alt={alt} loading="lazy" onError={() => setFailed(true)} /> : <div className="photo-fallback" aria-label="Image unavailable"><span>TRAVELINTEL</span></div>}
      {!src && !failed && <span className="photo-caption">Representative imagery</span>}
    </div>
  );
}

function CustomerHeader({ page, onNavigate, onAdmin, user, onLogout }) {
  const nav = [
    ["home", "Home"], ["discover", "Discover"], ["mood", "MoodMatch"],
    ["trip", "Trip Builder"], ["compare", "Compare"], ["hotels", "Hotels"],
    ["transport", "Transport"], ["weather", "WeatherWise"], ["reviews", "Reviews"],
    ["bookings", "My Bookings"],
  ];
  return (
    <>
      <div className="customer-topline"><span>Thoughtful travel, powered by real data.</span><span>DEMO · PLANNING REQUESTS ONLY</span></div>
      <header className="customer-header">
        <button className="customer-brand" onClick={() => onNavigate("home")} aria-label="TravelIntel home">
          <span className="customer-brand-mark"><i /><i /><i /></span>
          <span>Travel<span>Intel</span><small>DISCOVER WITH INSIGHT</small></span>
        </button>
        <nav className="customer-nav" aria-label="Customer navigation">
          {nav.map(([id, label]) => (
            <button key={id} className={page === id ? "active" : ""} onClick={() => onNavigate(id)}>{label}</button>
          ))}
        </nav>
        <button className="customer-admin-link" onClick={onAdmin}><span>▦</span> Admin Analytics</button>
        <div className="customer-account-tools">
          <span title={user.email}>Hi, <b>{user.name}</b></span>
          <button onClick={onLogout}>Log out</button>
        </div>
      </header>
    </>
  );
}

function DestinationCard({ destination, index, onDetails, onWishlist, saved, onTrip, onCompare, compareSelected }) {
  return (
    <article className="destination-card">
      <button className={`destination-save ${saved ? "saved" : ""}`} onClick={() => onWishlist(destination.id)} aria-label={saved ? "Remove from wishlist" : "Save to wishlist"} title={saved ? "Remove from wishlist" : "Save destination"}>{saved ? "♥" : "♡"}</button>
      <button className="destination-card-photo" onClick={() => onDetails(destination)} aria-label={`View ${destination.destination_name}`}>
        <Photo index={index} alt={`Representative landscape for ${destination.destination_name}`} />
        <span className="destination-region">{destination.region || destination.state}</span>
      </button>
      <div className="destination-card-body">
        <div className="destination-card-title"><div><p>{destination.state} · {destination.region}</p><h3>{destination.destination_name}</h3></div><span className="source-score">{number(destination.popularity_score, 1)}<small> source score</small></span></div>
        <p className="destination-description">{destination.unique_experiences || destination.user_reviews_summary || "Destination details are available in the source dataset."}</p>
        <div className="destination-tags">{list(destination.trip_types).slice(0, 3).map((tag) => <span key={tag}>{tag}</span>)}</div>
        <div className="destination-card-actions">
          <button className="customer-button subtle" onClick={() => onDetails(destination)}>View details</button>
          <button className="customer-button" onClick={() => onTrip(destination)}>Plan trip</button>
        </div>
        <button className={`compare-toggle ${compareSelected ? "selected" : ""}`} onClick={() => onCompare(destination.id)}>{compareSelected ? "✓ Added to compare" : "+ Add to compare"}</button>
      </div>
    </article>
  );
}

function PageTitle({ eyebrow, title, description, children }) {
  return (
    <section className="customer-page-title">
      <div><p className="customer-eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></div>
      {children}
    </section>
  );
}

function HomePage({ destinations, loading, error, onNavigate, onDetails, onWishlist, wishlist, onTrip, search, setSearch, onCompare }) {
  const featured = destinations.slice(0, 4);
  return (
    <>
      <section className="customer-hero">
        <div className="customer-hero-image" />
        <div className="customer-hero-content">
          <span className="hero-kicker">TRAVELINTEL · INTELLIGENT DISCOVERY</span>
          <h1>Find the trip<br />that feels like <em>you.</em></h1>
          <p>Explore real destination guides, discover a travel mood and shape a trip using information from the TravelIntel project datasets.</p>
          <form className="customer-search" onSubmit={(event) => { event.preventDefault(); onNavigate("discover"); }}>
            <label><span>Where to?</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search a place, region or interest" /></label>
            <button type="submit">Explore destinations <span>→</span></button>
          </form>
          <small className="customer-search-note">Travel suggestions use project data. No live inventory or bookings are offered.</small>
        </div>
        <div className="hero-photo-caption">Scenic representative imagery</div>
      </section>
      <section className="home-section">
        <div className="customer-section-heading"><div><p className="customer-eyebrow">YOUR NEXT CHAPTER</p><h2>Start with a feeling.</h2><p>Choose a mood to explore destinations with matching source-listed interests.</p></div><button className="customer-text-link" onClick={() => onNavigate("mood")}>Discover MoodMatch <span>→</span></button></div>
        <div className="mood-shortcuts">{MOODS.slice(0, 6).map((mood) => <button key={mood.id} onClick={() => onNavigate("mood")}><b>{mood.icon}</b><span>{mood.id}</span></button>)}</div>
      </section>
      <section className="home-section">
        <div className="customer-section-heading"><div><p className="customer-eyebrow">DESTINATIONS IN THE DATASET</p><h2>Places to begin.</h2></div><button className="customer-text-link" onClick={() => onNavigate("discover")}>All destinations <span>→</span></button></div>
        {error && <div className="customer-error">{error}</div>}
        {loading ? <div className="customer-message">Discovering destination records…</div> : featured.length ? <div className="destination-grid">{featured.map((item, index) => <DestinationCard key={item.id} destination={item} index={index} saved={wishlist.includes(item.id)} onWishlist={onWishlist} onDetails={onDetails} onTrip={onTrip} onCompare={onCompare} />)}</div> : <div className="customer-message">No destination records are available. Start the existing API to continue.</div>}
      </section>
      <section className="home-signature">
        <div><p className="customer-eyebrow">THE TRAVELINTEL DIFFERENCE</p><h2>Not just where.<br /><em>Why it fits you.</em></h2><p>Explore destination attributes, source-provided trip types and seasonal notes. Every suggestion makes its data basis clear.</p><button className="customer-button light" onClick={() => onNavigate("trip")}>Build a thoughtful trip <span>→</span></button></div>
        <div className="signature-list"><button onClick={() => onNavigate("mood")}><span>01</span><b>MoodMatch</b><small>Follow your travel instinct.</small><i>↗</i></button><button onClick={() => onNavigate("compare")}><span>02</span><b>Destination Face-Off</b><small>Compare what the records tell us.</small><i>↗</i></button><button onClick={() => onNavigate("weather")}><span>03</span><b>WeatherWise</b><small>Explore historical patterns, not forecasts.</small><i>↗</i></button></div>
      </section>
      <section className="home-section customer-trust-note"><b>Designed for transparency</b><span>Historical datasets are not live prices, availability, or forecasts. TravelIntel demo bookings are saved locally and do not reserve travel.</span><button className="customer-text-link" onClick={() => onNavigate("reviews")}>Read about the data <span>→</span></button></section>
    </>
  );
}

function DiscoverPage({ destinations, loading, error, wishlist, onWishlist, onDetails, onTrip, search, setSearch, compareIds, onCompare, onAlternatives }) {
  const [category, setCategory] = useState("All interests");
  const [sort, setSort] = useState("popular");
  const categories = useMemo(() => ["All interests", ...new Set(destinations.flatMap((item) => list(item.trip_types)))].sort((a, b) => a === "All interests" ? -1 : a.localeCompare(b)), [destinations]);
  const filtered = destinations
    .filter((item) => {
      const text = `${item.destination_name} ${item.region} ${item.state} ${item.unique_experiences} ${list(item.trip_types).join(" ")}`.toLowerCase();
      return text.includes(search.toLowerCase()) && (category === "All interests" || list(item.trip_types).includes(category));
    })
    .sort((a, b) => sort === "budget"
      ? Number(a.budgets?.budget?.[0] ?? Number.MAX_VALUE) - Number(b.budgets?.budget?.[0] ?? Number.MAX_VALUE)
      : Number(b.popularity_score ?? 0) - Number(a.popularity_score ?? 0));
  return (
    <>
      <PageTitle eyebrow="THE DESTINATION EDIT" title="Find your somewhere." description="Browse destination profiles from the project dataset. Descriptions, interests and budget ranges are source-provided." />
      <section className="discover-tools">
        <label className="customer-input"><span>Search destinations</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Try a destination, region or interest" /></label>
        <label className="customer-input"><span>Filter by trip type</span><select value={category} onChange={(event) => setCategory(event.target.value)}>{categories.map((option) => <option key={option}>{option}</option>)}</select></label>
        <label className="customer-input"><span>Sort by</span><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="popular">Source popularity score</option><option value="budget">Lowest source budget range</option></select></label>
      </section>
      <div className="discover-results-line"><span>{loading ? "Loading destination dataset…" : `${filtered.length} destination profiles`}</span><button className="customer-text-link" onClick={onAlternatives}>Find a smart alternative <span>→</span></button></div>
      {error && <div className="customer-error">{error}</div>}
      {filtered.length ? <div className="destination-grid">{filtered.map((item, index) => <DestinationCard key={item.id} destination={item} index={index} saved={wishlist.includes(item.id)} onWishlist={onWishlist} onDetails={onDetails} onTrip={onTrip} onCompare={onCompare} compareSelected={compareIds.includes(item.id)} />)}</div> : <div className="customer-message">{loading ? "Loading…" : "No source records match those filters."}</div>}
    </>
  );
}

function MoodPage({ destinations, onDetails, onTrip }) {
  const [mood, setMood] = useState("Adventure");
  const matches = destinations.filter((item) => isMoodMatch(item, mood))
    .sort((a, b) => mood === "Budget Escape"
      ? Number(a.budgets?.budget?.[0] ?? Number.MAX_VALUE) - Number(b.budgets?.budget?.[0] ?? Number.MAX_VALUE)
      : Number(b.popularity_score ?? 0) - Number(a.popularity_score ?? 0));
  return (
    <>
      <PageTitle eyebrow="MOODMATCH · SIGNATURE DISCOVERY" title="Where does your mood take you?" description="Pick a feeling. We’ll show destinations whose source-listed categories or traveler types match it—and explain why." />
      <div className="mood-selector">{MOODS.map((item) => <button key={item.id} className={mood === item.id ? "selected" : ""} onClick={() => setMood(item.id)}><b>{item.icon}</b><span>{item.id}</span><small>{item.text}</small></button>)}</div>
      <div className="discover-results-line"><span>{matches.length} matches supported by source tags</span><span className="data-note">Mood matching uses destination categories, not inferred personality.</span></div>
      {matches.length ? <div className="destination-grid">{matches.map((destination, index) => <article className="destination-card mood-result-card" key={destination.id}><Photo index={index} alt={`Representative imagery for ${destination.destination_name}`} /><div className="destination-card-body"><p className="customer-eyebrow">MATCHED TO {mood.toUpperCase()}</p><h3>{destination.destination_name}</h3><span className="destination-location">{destination.district}, {destination.state}</span><p className="match-reason">{moodReason(destination, mood)}</p>{destination.user_reviews_summary && <blockquote>“{destination.user_reviews_summary}”<small>Source-provided review summary</small></blockquote>}<div className="destination-card-actions"><button className="customer-button subtle" onClick={() => onDetails(destination)}>View details</button><button className="customer-button" onClick={() => onTrip(destination)}>Add to trip</button></div></div></article>)}</div> : <div className="customer-message">No destination has source-listed tags matching “{mood}”. Try another mood; we will not infer unsupported matches.</div>}
    </>
  );
}

function DestinationDetails({ destination, index, onBack, onWishlist, saved, onTrip, onCompare, onAlternatives }) {
  if (!destination) return <div className="customer-message">Select a destination from Discover to view its profile.</div>;
  return (
    <div className="destination-detail">
      <button className="back-link" onClick={onBack}>← All destinations</button>
      <div className="destination-detail-hero"><Photo index={index} alt={`Representative imagery for ${destination.destination_name}`} /><div><p className="customer-eyebrow">{destination.region} · {destination.state}</p><h1>{destination.destination_name}</h1><p>{destination.unique_experiences}</p><div className="destination-tags">{list(destination.trip_types).map((tag) => <span key={tag}>{tag}</span>)}</div><div className="detail-actions"><button className="customer-button" onClick={() => onTrip(destination)}>Build a trip</button><button className="customer-button subtle" onClick={() => onWishlist(destination.id)}>{saved ? "♥ Saved" : "♡ Save to wishlist"}</button><button className="customer-button subtle" onClick={() => onCompare(destination.id)}>Compare</button><button className="customer-text-link" onClick={() => onAlternatives(destination)}>Find alternatives</button></div></div></div>
      <div className="destination-detail-grid">
        <article className="travel-info-card"><p className="customer-eyebrow">THE LOCAL EDIT</p><h2>Places & experiences</h2><h3>Primary attractions</h3><ul>{list(destination.primary_attractions).map((place) => <li key={place}>{place}</li>)}</ul><h3>Activities</h3><div className="detail-tag-list">{list(destination.activities_available).map((activity) => <span key={activity}>{activity}</span>)}</div>{destination.user_reviews_summary && <><h3>Source-provided visitor summary</h3><p>{destination.user_reviews_summary}</p></>}</article>
        <article className="travel-info-card"><p className="customer-eyebrow">PLAN WITH CONTEXT</p><h2>Know before you go</h2><dl className="destination-facts"><div><dt>Best seasons</dt><dd>{list(destination.best_seasons).join(", ") || "Not in source data"}</dd></div><div><dt>Popular period</dt><dd>{destination.peak_tourist_season || "Not in source data"}</dd></div><div><dt>Accessibility</dt><dd>{destination.accessibility || "Not in source data"}</dd></div><div><dt>Safety rating</dt><dd>{destination.safety_rating == null ? "Not in source data" : `${number(destination.safety_rating, 1)} / 10`}</dd></div><div><dt>Nearest airport</dt><dd>{destination.nearest_airport_name || "Not in source data"}</dd></div></dl><p className="detail-caveat">Source destination information is descriptive and may not reflect current conditions. Check official guidance before travel.</p></article>
        <article className="travel-info-card"><p className="customer-eyebrow">SOURCE BUDGET RANGES</p><h2>Daily budget context</h2><div className="budget-options">{[["budget", "Budget"], ["mid_range", "Mid-range"], ["luxury", "Luxury"]].map(([key, title]) => <div key={key}><span>{title}</span><b>{formatBudget(destination.budgets?.[key])}</b></div>)}</div><p className="detail-caveat">These ranges are from the destination dataset. Currency is not specified there; values are not live quotes.</p></article>
      </div>
    </div>
  );
}

function TripBuilder({ destinations, initialDestination, preferences, onPreferences, onSaveTrip, onBooking, onOpenPage }) {
  const [origin, setOrigin] = useState(preferences.origin || "");
  const [destinationId, setDestinationId] = useState(initialDestination?.id ?? destinations[0]?.id ?? "");
  const [days, setDays] = useState(preferences.days || 5);
  const [travellers, setTravellers] = useState(preferences.travellers || 2);
  const [budgetTier, setBudgetTier] = useState(preferences.budgetTier || "budget");
  const [mood, setMood] = useState(preferences.mood || "Adventure");
  const [interests, setInterests] = useState(preferences.interests || []);
  const [saved, setSaved] = useState(false);
  const destination = destinations.find((item) => String(item.id) === String(destinationId));
  const itinerary = destination?.suggested_itinerary
    ? destination.suggested_itinerary.split(/(?=Day\s*\d+)/i).map((item) => item.trim()).filter(Boolean)
    : [];
  const totalRange = destination?.budgets?.[budgetTier];
  const tripRange = Array.isArray(totalRange) ? totalRange.map((amount) => amount * Number(days) * Number(travellers)) : null;
  const availableInterests = useMemo(() => [...new Set(destinations.flatMap((item) => list(item.trip_types)))].sort(), [destinations]);
  const toggleInterest = (interest) => setInterests((current) => current.includes(interest) ? current.filter((value) => value !== interest) : [...current, interest]);
  const savePlan = () => {
    onPreferences({ origin, days: Number(days), travellers: Number(travellers), budgetTier, mood, interests });
    onSaveTrip({
      destinationId: destination?.id,
      destinationName: destination?.destination_name,
      origin,
      days: Number(days),
      travellers: Number(travellers),
      budgetTier,
      mood,
      interests,
      itinerary,
      savedAt: new Date().toISOString(),
    });
    setSaved(true);
  };
  return (
    <>
      <PageTitle eyebrow="SMART TRIP BUILDER" title="A trip with room to be yours." description="Use the itinerary and destination facts provided in the source dataset. Save a draft plan or submit a clearly labelled demo request." />
      <div className="trip-builder-grid">
        <form className="trip-form" onSubmit={(event) => { event.preventDefault(); savePlan(); }}>
          <p className="customer-eyebrow">YOUR TRIP BRIEF</p>
          <label className="customer-input"><span>Starting location</span><input value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="City or region" /></label>
          <label className="customer-input"><span>Destination</span><select value={destinationId} onChange={(event) => { setDestinationId(event.target.value); setSaved(false); }} required>{destinations.map((item) => <option key={item.id} value={item.id}>{item.destination_name} · {item.state}</option>)}</select></label>
          <div className="trip-number-fields"><label className="customer-input"><span>Duration · days</span><input type="number" min="1" max="30" value={days} required onChange={(event) => setDays(event.target.value)} /></label><label className="customer-input"><span>Travellers</span><input type="number" min="1" max="20" value={travellers} required onChange={(event) => setTravellers(event.target.value)} /></label></div>
          <label className="customer-input"><span>Source budget range</span><select value={budgetTier} onChange={(event) => setBudgetTier(event.target.value)}><option value="budget">Budget</option><option value="mid_range">Mid-range</option><option value="luxury">Luxury</option></select></label>
          <label className="customer-input"><span>Travel mood</span><select value={mood} onChange={(event) => setMood(event.target.value)}>{MOODS.map((item) => <option key={item.id}>{item.id}</option>)}</select></label>
          <fieldset className="trip-interest-picker"><legend>Interests from source categories</legend><div>{availableInterests.slice(0, 18).map((interest) => <label key={interest}><input type="checkbox" checked={interests.includes(interest)} onChange={() => toggleInterest(interest)} />{interest}</label>)}</div></fieldset>
          <button className="customer-button trip-save-button" type="submit">Save this trip plan <span>→</span></button>
          {saved && <p className="form-success" role="status">Trip draft saved on this browser.</p>}
        </form>
        <div className="trip-itinerary">
          <div className="trip-itinerary-top"><p className="customer-eyebrow">YOUR SUGGESTED ROUTE</p><span>DATA-SOURCED DRAFT</span></div>
          {destination ? <><div className="trip-destination-intro"><Photo index={destination.id} alt={`Representative imagery for ${destination.destination_name}`} /><div><h2>{destination.destination_name}</h2><p>{destination.region} · {number(days)} days · {number(travellers)} travellers</p></div></div>
            <h3>Itinerary details</h3>
            {itinerary.length ? <div className="itinerary-days">{itinerary.map((item, index) => <article key={`${index}-${item}`}><span>{String(index + 1).padStart(2, "0")}</span><p>{item}</p></article>)}</div> : <p className="data-limitation">No day-by-day itinerary is provided for this destination. Use its sourced attractions as a starting point.</p>}
            <div className="trip-places"><b>Suggested places in source data</b><div>{list(destination.primary_attractions).slice(0, 8).map((place) => <span key={place}>{place}</span>)}</div></div>
            <div className="trip-budget"><span>Indicative total range · {budgetTier.replace("_", " ")}</span><b>{tripRange ? `${number(tripRange[0])}–${number(tripRange[1])}` : "Not provided"}</b><small>Source daily range × {number(days)} days × {number(travellers)} travellers. Currency is unspecified; accommodation, transport and live prices are not included.</small></div>
            <div className="detail-actions">
              <button className="customer-button subtle" onClick={() => onBooking({ type: "trip plan", name: `${number(days)}-day trip to ${destination.destination_name}`, location: destination.state, detail: `Source itinerary and budget context only · ${tripRange ? `${number(tripRange[0])}–${number(tripRange[1])} in unspecified currency` : "budget not provided"} · no travel or lodging reserved.`, itinerary, days: Number(days), travellers: Number(travellers), origin, budgetTier, budgetRange: tripRange })}>Review trip request <span>→</span></button>
              <button className="customer-button subtle" onClick={() => onOpenPage("budget", destination)}>Estimate budget</button>
              <button className="customer-button subtle" onClick={() => onOpenPage("map", destination)}>Open map</button>
              <button className="customer-button subtle" onClick={() => onOpenPage("hotels", destination)}>Search hotels</button>
              <button className="customer-button subtle" onClick={() => onOpenPage("transport", destination)}>Search transport</button>
            </div>
          </> : <div className="customer-message">Choose a destination to build a data-backed draft.</div>}
        </div>
      </div>
    </>
  );
}

function compareScore(destination, interests) {
  if (!interests.length) return null;
  const categories = list(destination.trip_types).map(normalize);
  const matches = interests.filter((interest) => categories.includes(normalize(interest)));
  return { matches, total: interests.length };
}

function ComparePage({ destinations, compareIds, onCompare, onTrip, onAlternatives }) {
  const [interests, setInterests] = useState([]);
  const compared = compareIds.map((id) => destinations.find((item) => String(item.id) === String(id))).filter(Boolean);
  const categories = [...new Set(destinations.flatMap((item) => list(item.trip_types)))].slice(0, 18);
  return (
    <>
      <PageTitle eyebrow="DESTINATION FACE-OFF" title="Two places. Your kind of trip." description="Compare two or three destination profiles side by side. Match scores transparently count exact source-listed interest tags." />
      <div className="compare-pickers">{[0, 1, 2].map((slot) => <label className="customer-input" key={slot}><span>Destination {slot + 1}{slot < 2 ? " · required" : " · optional"}</span><select value={compareIds[slot] ?? ""} onChange={(event) => onCompare(event.target.value, slot)}><option value="">Select a destination</option>{destinations.map((item) => <option key={item.id} value={item.id}>{item.destination_name} · {item.state}</option>)}</select></label>)}</div>
      <div className="compare-interest-panel"><div><b>What matters to you?</b><small>Optional: select interest tags to calculate a match score.</small></div><div className="compare-interest-tags">{categories.map((category) => <label key={category}><input type="checkbox" checked={interests.includes(category)} onChange={() => setInterests((current) => current.includes(category) ? current.filter((item) => item !== category) : [...current, category])} />{category}</label>)}</div></div>
      {compared.length >= 2 ? <div className="compare-grid">{compared.map((destination, index) => {
        const score = compareScore(destination, interests);
        return <article className="compare-card" key={destination.id}><Photo index={destination.id} alt={`Representative imagery for ${destination.destination_name}`} /><p className="customer-eyebrow">{destination.region} · {destination.state}</p><h2>{destination.destination_name}</h2><dl className="compare-facts"><div><dt>Source popularity</dt><dd>{number(destination.popularity_score, 1)}</dd></div><div><dt>Safety rating</dt><dd>{destination.safety_rating == null ? "Not available" : `${number(destination.safety_rating, 1)} / 10`}</dd></div><div><dt>Trip interests</dt><dd>{list(destination.trip_types).join(", ") || "Not available"}</dd></div><div><dt>Best seasons</dt><dd>{list(destination.best_seasons).join(", ") || "Not available"}</dd></div><div><dt>Budget · source range</dt><dd>{formatBudget(destination.budgets?.budget)}</dd></div></dl>{score && <div className="match-score"><b>{Math.round(score.matches.length / score.total * 100)}%</b><span>{score.matches.length} of {score.total} selected interest tags match exactly.</span></div>}<div className="destination-card-actions"><button className="customer-button" onClick={() => onTrip(destination)}>Plan this trip</button><button className="customer-button subtle" onClick={() => onAlternatives(destination)}>Similar alternatives</button></div></article>;
      })}</div> : <div className="customer-message">Select at least two destinations to compare their source records.</div>}
      <p className="data-limitation">Destination profiles and tourism-observation ratings come from separate sources without a verified join, so they are not combined in this comparison.</p>
    </>
  );
}

function AlternativesPage({ destinations, selectedDestination, onSelectDestination, onDetails, onTrip }) {
  const source = selectedDestination ?? destinations[0];
  const alternatives = useMemo(() => {
    if (!source) return [];
    const sourceTypes = list(source.trip_types).map(normalize);
    return destinations.filter((item) => item.id !== source.id)
      .map((item) => {
        const shared = list(item.trip_types).filter((type) => sourceTypes.includes(normalize(type)));
        const sameRegion = item.region && item.region === source.region;
        const budgetGap = Math.abs(Number(item.budgets?.budget?.[0] ?? 0) - Number(source.budgets?.budget?.[0] ?? 0));
        return { item, shared, sameRegion, budgetGap };
      })
      .sort((a, b) => b.shared.length - a.shared.length || Number(b.sameRegion) - Number(a.sameRegion) || a.budgetGap - b.budgetGap)
      .slice(0, 8);
  }, [destinations, source]);
  return (
    <>
      <PageTitle eyebrow="SMART ALTERNATIVE FINDER" title="A different way to get there." description="Find alternatives by shared source-listed trip types, region and budget range. No predictive similarity model is claimed." />
      <label className="customer-input alternative-source"><span>Starting destination</span><select value={source?.id ?? ""} onChange={(event) => onSelectDestination(destinations.find((item) => String(item.id) === event.target.value))}>{destinations.map((item) => <option key={item.id} value={item.id}>{item.destination_name} · {item.state}</option>)}</select></label>
      {source && <p className="alternative-explanation">Alternatives to <b>{source.destination_name}</b> are ordered by shared trip-type tags, then same region, then closeness of the provided entry-budget minimum.</p>}
      <div className="destination-grid">{alternatives.map(({ item, shared, sameRegion, budgetGap }, index) => <article className="alternative-card" key={item.id}><Photo index={item.id} alt={`Representative imagery for ${item.destination_name}`} /><div><p className="customer-eyebrow">SOURCE ATTRIBUTE MATCH</p><h3>{item.destination_name}</h3><p>{shared.length ? `Shares ${shared.join(", ")} trip type${shared.length > 1 ? "s" : ""}.` : sameRegion ? `Located in the same source region: ${item.region}.` : `A different source-listed destination with an available budget profile.`}</p><small>{formatBudget(item.budgets?.budget)}{budgetGap === 0 ? " · same entry budget" : ""}</small><div className="destination-card-actions"><button className="customer-button subtle" onClick={() => onDetails(item)}>View details</button><button className="customer-button" onClick={() => onTrip(item)}>Plan trip</button></div></div></article>)}</div>
    </>
  );
}

function HotelsPage({ hotels, loading, error, city, setCity, search, setSearch, onSelectHotel }) {
  const [checkIn, setCheckIn] = useState("");
  const [checkOut, setCheckOut] = useState("");
  const [guests, setGuests] = useState(1);
  const [rooms, setRooms] = useState(1);
  const [roomType, setRoomType] = useState("");
  const [amenity, setAmenity] = useState("");
  const [maxHistoricalPrice, setMaxHistoricalPrice] = useState("");
  const invalidDates = checkIn && checkOut && checkOut <= checkIn;
  const nights = nightCount(checkIn, checkOut);
  const validGuests = Number.isInteger(Number(guests)) && Number(guests) >= 1 && Number(guests) <= 20;
  const validRooms = Number.isInteger(Number(rooms)) && Number(rooms) >= 1 && Number(rooms) <= 10;
  const matchingHotels = validGuests
    ? hotels.filter((hotel) =>
      hotel.accommodates &&
      Number(hotel.accommodates) >= Number(guests) &&
      (!roomType || hotel.room_type === roomType) &&
      (!amenity || list(hotel.amenities).some((item) => item.toLowerCase() === amenity.toLowerCase())) &&
      (!maxHistoricalPrice || (
        historicalPriceValue(hotel.historical_price) !== null &&
        historicalPriceValue(hotel.historical_price) <= Number(maxHistoricalPrice)
      )),
    )
    : [];
  const roomTypes = [...new Set(hotels.map((hotel) => hotel.room_type).filter(Boolean))].sort();
  const amenities = [...new Set(hotels.flatMap((hotel) => list(hotel.amenities)))].sort();
  const selectHotel = (hotel) => onSelectHotel({
    type: "Hotel planning request",
    bookingType: "hotel",
    name: hotel.name || "Accommodation listing",
    location: [hotel.city, hotel.neighbourhood].filter(Boolean).join(" · "),
    detail: `Historical listing only · ${hotel.room_type || "Room type not recorded"} · ${guests} guest(s), ${rooms} room(s) requested · stay ${checkIn || "date not set"} to ${checkOut || "date not set"} · historical rate ${hotel.historical_price || "not in source"} · current availability not verified.`,
    hotel: {
      id: hotel.id,
      city: hotel.city,
      neighbourhood: hotel.neighbourhood,
      roomType: hotel.room_type,
      guests: Number(guests),
      rooms: Number(rooms),
      checkIn,
      checkOut,
      historicalPrice: hotel.historical_price,
      snapshotDate: hotel.snapshot_date,
      snapshotAvailability30: hotel.snapshot_availability_30,
      amenities: list(hotel.amenities),
    },
  });
  return (
    <>
      <PageTitle eyebrow="STAYS · SOURCE LISTINGS" title="Places to stay." description="Search existing accommodation snapshots by destination, stay dates, and guest capacity." />
      <div className="browse-tools">
        <label className="customer-input"><span>Hotel or neighbourhood</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search name or neighbourhood" /></label>
        <label className="customer-input"><span>Destination city</span><select value={city} onChange={(event) => setCity(event.target.value)}><option value="">Both cities</option><option>Boston</option><option>Seattle</option></select></label>
        <label className="customer-input"><span>Check-in</span><input type="date" value={checkIn} onChange={(event) => setCheckIn(event.target.value)} /></label>
        <label className="customer-input"><span>Check-out</span><input type="date" min={checkIn || undefined} value={checkOut} onChange={(event) => setCheckOut(event.target.value)} /></label>
        <label className="customer-input"><span>Guests</span><input type="number" min="1" max="20" step="1" value={guests} onChange={(event) => setGuests(event.target.value)} /></label>
        <label className="customer-input"><span>Rooms requested</span><input type="number" min="1" max="10" step="1" value={rooms} onChange={(event) => setRooms(event.target.value)} /></label>
        <label className="customer-input"><span>Room type · source listing</span><select value={roomType} onChange={(event) => setRoomType(event.target.value)}><option value="">All room types</option>{roomTypes.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="customer-input"><span>Amenity · source listing</span><select value={amenity} onChange={(event) => setAmenity(event.target.value)}><option value="">Any amenity</option>{amenities.map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="customer-input"><span>Max historical nightly rate · source currency</span><input type="number" min="0" step="0.01" value={maxHistoricalPrice} onChange={(event) => setMaxHistoricalPrice(event.target.value)} placeholder="No limit" /></label>
      </div>
      {invalidDates && <div className="customer-error" role="alert">Check-out must be after check-in.</div>}
      {!validGuests && <div className="customer-error" role="alert">Enter a whole number of guests from 1 to 20.</div>}
      {!validRooms && <div className="customer-error" role="alert">Enter a whole number of rooms from 1 to 10.</div>}
      <div className="historical-notice"><b>Historical data only</b><span>Location, room types, amenities and prices come from stored listing snapshots. Dates are collected for your request, but the snapshots cannot confirm date availability. Displayed prices are not quotes; requests do not reserve rooms.</span></div>
      {error && <div className="customer-error">{error}</div>}
      {loading ? <div className="customer-message">Loading accommodation snapshots…</div> : !validGuests ? <div className="customer-message">Enter a valid guest count to filter the source listings.</div> : matchingHotels.length ? <div className="hotel-grid">{matchingHotels.map((hotel, index) => <article className="hotel-card" key={`${hotel.city}-${hotel.id}`}><Photo src={hotel.image_url} index={index} alt={`Source listing photo for ${hotel.name}`} /><div className="hotel-body"><div className="hotel-city">{hotel.city} · {hotel.neighbourhood || "Neighbourhood not listed"}</div><h3>{hotel.name || "Unnamed source listing"}</h3><p>{hotel.summary || hotel.description || "No description in this source record."}</p><div className="hotel-data-row"><span>{hotel.property_type || "Property type unavailable"} · {hotel.room_type || "Room type unavailable"}</span><span>{hotel.accommodates ? `Sleeps ${number(hotel.accommodates)} · source capacity` : "Capacity unavailable"}</span></div>{list(hotel.amenities).length > 0 && <small className="snapshot-date">Source amenities: {list(hotel.amenities).slice(0, 5).join(", ")}</small>}<div className="hotel-price-row"><div><b>{hotel.historical_price || "Price not recorded"}</b><small>historical nightly price</small><small>{nights && validRooms && !invalidDates ? `${historicalStayTotal(hotel.historical_price, nights, Number(rooms)) || "Not in source"} · historical estimate for ${nights} night(s) × ${rooms} room(s)` : "Select valid dates to estimate from the historical rate"}</small></div><div><b>{hotel.rating ?? "—"}</b><small>{hotel.review_count ? `${number(hotel.review_count)} source reviews` : "rating snapshot"}</small></div></div><small className="snapshot-date">Snapshot: {hotel.snapshot_date || "not recorded"} · {hotel.snapshot_availability_30 == null || hotel.snapshot_availability_30 === "" ? "Availability not recorded" : `${number(hotel.snapshot_availability_30)} of next 30 days listed available in snapshot`} · Cancellation: {hotel.snapshot_cancellation_policy || "not in source"}</small><small className="snapshot-date">Minimum stay: {number(hotel.snapshot_minimum_nights)} night(s) · source record</small><button className="customer-button full" onClick={() => selectHotel(hotel)} disabled={!validRooms || Boolean(invalidDates)} title="Adds this historical listing to a planning request only">Add to trip request · not a reservation</button></div></article>)}</div> : <div className="customer-message">{hotels.length ? "No source listings with sufficient recorded capacity." : "No matching listing records are available."}</div>}
    </>
  );
}

function TransportPage({ records, notice, loading, error, onBooking }) {
  const [origin, setOrigin] = useState("");
  const [destination, setDestination] = useState("");
  const [travelDate, setTravelDate] = useState("");
  const [passengers, setPassengers] = useState(1);
  const [category, setCategory] = useState("commute");
  const [sortBy, setSortBy] = useState("date");
  const [searched, setSearched] = useState(false);
  const [locationNotice, setLocationNotice] = useState("");
  const validPassengers = Number.isInteger(Number(passengers)) && Number(passengers) >= 1 && Number(passengers) <= 20;
  const matchingRecords = category === "commute" && !origin.trim()
    ? records.filter((record) =>
      (!destination || String(record.going_to || "").toLowerCase().includes(destination.trim().toLowerCase())) &&
      (!travelDate || String(record.date || "").slice(0, 10) === travelDate),
    )
    : [];
  const matches = [...matchingRecords].sort((a, b) => {
    if (sortBy === "duration" || sortBy === "distance") {
      return (Number(a[sortBy === "duration" ? "total_time" : "distance"]) || Infinity) -
        (Number(b[sortBy === "duration" ? "total_time" : "distance"]) || Infinity);
    }
    return String(b.date || "").localeCompare(String(a.date || ""));
  });
  const categoryUnavailable = {
    bus: "No bus routes, schedules, fares, or ticket provider are present in the existing data.",
    train: "No railway routes, train schedules, fares, or ticket provider are present in the existing data.",
    flight: "No flight schedules, fares, or ticket provider are present in the existing data.",
    rental: "No rental cars, bikes, scooters, providers, rates, or availability are present in the existing TravelIntel data.",
    taxi: "No taxi providers, pickup points, fares, or availability are present in the existing data.",
  }[category];
  const nearbyKinds = {
    bus: ["Bus stations", "Bus terminals"],
    train: ["Railway stations"],
    flight: ["Airports"],
    rental: ["Car rental", "Bike rental", "Scooter rental"],
    taxi: ["Taxi stands", "Taxi services"],
  }[category] || [];
  const nearbyLocation = destination.trim() || origin.trim();
  const today = new Date().toISOString().slice(0, 10);
  const canRequest = category !== "commute" && validPassengers && origin.trim() &&
    destination.trim() && travelDate >= today;
  const submitRequest = () => onBooking({
    type: `${category[0].toUpperCase()}${category.slice(1)} planning request`,
    bookingType: category,
    name: `${category[0].toUpperCase()}${category.slice(1)}: ${origin.trim()} to ${destination.trim()}`,
    origin: origin.trim(),
    location: destination.trim(),
    detail: `Customer request only · ${travelDate} · ${passengers} passenger(s) · no route, schedule, fare, provider or availability has been verified.`,
    travelDate,
    travellers: Number(passengers),
    transport: { category, origin: origin.trim(), destination: destination.trim(), travelDate, passengers: Number(passengers) },
  });
  const useCurrentLocation = () => {
    if (!navigator.geolocation) {
      setLocationNotice("Location permission is not available in this browser. Enter an origin manually.");
      return;
    }
    setLocationNotice("Requesting location permission…");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setOrigin(`${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}`);
        setLocationNotice("Current coordinates added as the request origin; no route is verified.");
      },
      () => setLocationNotice("Location was not shared. Enter an origin manually."),
      { timeout: 10000 },
    );
  };
  return (
    <>
      <PageTitle eyebrow="TRANSPORT · SEARCH & DISCOVERY" title="The journey between." description="Search source-backed commute observations or check which transport categories have data." />
      <form className="browse-tools" onSubmit={(event) => { event.preventDefault(); setSearched(true); }}>
        <label className="customer-input"><span>Origin</span><input value={origin} onChange={(event) => setOrigin(event.target.value)} placeholder="Starting location" /></label>
        <button className="customer-button subtle" type="button" onClick={useCurrentLocation}>Use my location</button>
        <label className="customer-input"><span>Destination</span><input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="Destination" /></label>
        <label className="customer-input"><span>Travel date</span><input type="date" min={today} value={travelDate} onChange={(event) => setTravelDate(event.target.value)} /></label>
        <label className="customer-input"><span>Passengers</span><input type="number" min="1" max="20" step="1" value={passengers} onChange={(event) => setPassengers(event.target.value)} required /></label>
        <label className="customer-input"><span>Transport category</span><select value={category} onChange={(event) => setCategory(event.target.value)}><option value="commute">Historical commute observations</option><option value="bus">Bus</option><option value="train">Train</option><option value="flight">Flight</option><option value="rental">Car / bike / scooter rental</option><option value="taxi">Taxi / cab</option></select></label>
        <label className="customer-input"><span>Sort observations</span><select value={sortBy} onChange={(event) => setSortBy(event.target.value)}><option value="date">Most recent source date</option><option value="duration">Shortest recorded duration</option><option value="distance">Shortest recorded distance</option><option value="price" disabled>Price · not in source</option></select></label>
        <button className="customer-button" type="submit">Search source data</button>
      </form>
      {locationNotice && <p className="data-limitation" role="status">{locationNotice}</p>}
      <div className="historical-notice"><b>Source vs demo</b><span>Historical commute rows are actual warehouse observations. Other route searches are planning requests only: live providers, routes, schedules, fares and availability are not connected. No demo schedules or prices are presented as real.</span></div>
      {error && <div className="customer-error">{error}</div>}
      {locationNotice && <p className="data-limitation" role="status">{locationNotice}</p>}
      {loading ? <div className="customer-message">Loading source records…</div> : searched && !validPassengers ? <div className="customer-message">Enter a whole number of passengers from 1 to 20.</div> : searched && category === "commute" && origin.trim() ? <div className="customer-message">No exact route can be verified because the existing records do not include an origin.</div> : searched && category === "commute" && travelDate && !matches.length ? <div className="customer-message">No historical observations match this source date and destination.</div> : searched && category === "commute" && matches.length ? <><p className="data-limitation">Historical observations match the destination text{travelDate ? ` and source date ${travelDate}` : ""}. Passenger count is not represented in the source; these are not bookable options or schedules.</p><div className="transport-records">{matches.map((record, index) => <article key={`${record.date}-${index}`}><div className="transport-date"><b>Commute observation</b><span>{record.date || "Date not recorded"}</span></div><div className="transport-route"><span>Destination in source</span><b>{record.going_to || "Not recorded"}</b><small>Origin · not in source</small></div><div className="transport-metrics"><span><b>{number(record.distance, 1)}</b><small>distance · source units</small></span><span><b>{number(record.total_time, 1)}</b><small>observed duration · source units</small></span><span><b>Not in source</b><small>fare / availability / type</small></span></div></article>)}</div><p className="data-limitation">{notice}</p></> : searched && category !== "commute" ? <section className="customer-content-card"><h2>{categoryUnavailable}</h2><p>Use Google Maps to explore external nearby listings, or save your route details as a customer planning request. This does not reserve anything.</p>{nearbyLocation && <div className="map-attraction-list">{nearbyKinds.map((kind) => <a key={kind} href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${kind} near ${nearbyLocation}`)}`} target="_blank" rel="noreferrer">{kind} near {nearbyLocation} ↗</a>)}</div>}<button className="customer-button" type="button" onClick={submitRequest} disabled={!canRequest}>Save transport planning request</button>{!canRequest && <small className="data-limitation">Enter an origin, destination, future travel date and 1–20 passengers to save a request.</small>}</section> : searched ? <div className="customer-message">No matching historical destination observations.</div> : <div className="customer-message">Search to view historical commute observations or explore nearby transport categories.</div>}
    </>
  );
}

function BudgetPlanner({ destinations, initialDestination, onSaveTrip, onNavigate, bookings = [] }) {
  const [destinationId, setDestinationId] = useState(initialDestination?.id ?? destinations[0]?.id ?? "");
  const [days, setDays] = useState(1);
  const [travellers, setTravellers] = useState(1);
  const [tier, setTier] = useState("budget");
  const [transportType, setTransportType] = useState("Not selected");
  const [currency, setCurrency] = useState("INR");
  const [expenses, setExpenses] = useState({
    transport: "",
    accommodation: "",
    food: "",
    local: "",
    activities: "",
    miscellaneous: "",
  });
  const [hotels, setHotels] = useState([]);
  const [hotelLoading, setHotelLoading] = useState(true);
  const [hotelError, setHotelError] = useState("");
  const [hotelId, setHotelId] = useState("");
  const [estimateReferences, setEstimateReferences] = useState([]);
  const destination = destinations.find((item) => String(item.id) === String(destinationId));
  const selectedHotel = hotels.find((hotel) => String(hotel.id) === hotelId);
  const expenseItems = [
    ["transport", "Transport · your estimate"],
    ["accommodation", "Accommodation · your estimate"],
    ["food", "Food"],
    ["local", "Local travel"],
    ["activities", "Activities and sightseeing"],
    ["miscellaneous", "Shopping and miscellaneous"],
  ];
  const manualTotal = expenseItems.reduce((sum, [key]) => sum + Math.max(0, Number(expenses[key]) || 0), 0);
  const availableBookingEstimates = bookings.filter((booking) =>
    booking.bookingStatus !== "cancelled_request" &&
    booking.priceBreakdown?.customerEstimate !== null &&
    booking.priceBreakdown?.customerEstimate !== undefined &&
    booking.priceBreakdown?.currency === currency,
  );
  const selectedBookingEstimates = availableBookingEstimates.filter((booking) => estimateReferences.includes(booking.reference));
  const bookingEstimateTotal = selectedBookingEstimates.reduce(
    (sum, booking) => sum + Number(booking.priceBreakdown.customerEstimate),
    0,
  );
  const total = manualTotal + bookingEstimateTotal;
  const hasExpenses = expenseItems.some(([key]) => expenses[key] !== "") || selectedBookingEstimates.length > 0;
  const validDays = Number.isInteger(Number(days)) && Number(days) >= 1 && Number(days) <= 90;
  const validTravellers = Number.isInteger(Number(travellers)) && Number(travellers) >= 1 && Number(travellers) <= 20;
  const perPerson = validTravellers ? total / Number(travellers) : null;
  const sourceRange = destination?.budgets?.[tier];

  useEffect(() => {
    if (destinations.length && !destinations.some((item) => String(item.id) === String(destinationId))) {
      setDestinationId(initialDestination?.id ?? destinations[0].id);
    }
  }, [destinations, destinationId, initialDestination]);

  useEffect(() => {
    let active = true;
    getJson("/api/customer/accommodations?limit=60")
      .then((result) => { if (active) setHotels(result.accommodations); })
      .catch((cause) => { if (active) setHotelError(cause.message); })
      .finally(() => { if (active) setHotelLoading(false); });
    return () => { active = false; };
  }, []);

  const updateExpense = (key, value) => setExpenses((current) => ({
    ...current,
    [key]: value === "" ? "" : Math.max(0, Number(value) || 0),
  }));
  const saveEstimate = () => {
    if (!destination || !validDays || !validTravellers || !hasExpenses) return;
    onSaveTrip({
      destinationId: destination?.id,
      destinationName: destination?.destination_name,
      days: Number(days),
      travellers: Number(travellers),
      budgetTier: tier,
      transportType,
      hotelName: selectedHotel?.name || "",
      expenses: Object.fromEntries(expenseItems.map(([key]) => [key, Math.max(0, Number(expenses[key]) || 0)])),
      budgetCurrency: currency,
      totalEstimate: total,
      bookingEstimates: selectedBookingEstimates.map((booking) => ({
        reference: booking.reference,
        amount: Number(booking.priceBreakdown.customerEstimate),
        currency,
      })),
      savedAt: new Date().toISOString(),
    });
  };

  return (
    <>
      <PageTitle eyebrow="TRIP BUDGET · ESTIMATES" title="Plan the cost, before you go." description="Combine your own expense estimates with source-provided destination ranges. No amounts here are booking quotes." />
      <div className="budget-planner-grid">
        <section className="customer-content-card">
          <label className="customer-input"><span>Destination</span><select value={destinationId} onChange={(event) => setDestinationId(event.target.value)}>{destinations.map((item) => <option key={item.id} value={item.id}>{item.destination_name} · {item.state}</option>)}</select></label>
          <div className="trip-number-fields">
            <label className="customer-input"><span>Days</span><input type="number" min="1" max="90" step="1" value={days} onChange={(event) => setDays(event.target.value)} /></label>
            <label className="customer-input"><span>Travellers</span><input type="number" min="1" max="20" step="1" value={travellers} onChange={(event) => setTravellers(event.target.value)} /></label>
          </div>
          <label className="customer-input"><span>Expense currency for your estimates (changing it does not convert values)</span><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option></select></label>
          <label className="customer-input"><span>Transport choice</span><select value={transportType} onChange={(event) => setTransportType(event.target.value)}><option>Not selected</option><option>Bus</option><option>Train</option><option>Flight</option><option>Rental vehicle</option><option>Taxi / local cab</option><option>Other / personal vehicle</option></select></label>
          <label className="customer-input"><span>Accommodation source listing · context only</span><select value={hotelId} onChange={(event) => setHotelId(event.target.value)}><option value="">No listing selected</option>{hotels.map((hotel) => <option key={`${hotel.city}-${hotel.id}`} value={hotel.id}>{hotel.name || "Unnamed listing"} · {hotel.city}</option>)}</select></label>
          {hotelLoading && <p className="data-limitation">Loading actual historical listing choices…</p>}
          {hotelError && <p className="customer-error">{hotelError}</p>}
          {selectedHotel && <p className="data-limitation">Selected source listing: {selectedHotel.room_type || "room type not recorded"} · historical nightly price {selectedHotel.historical_price || "not in source"} · not an availability or rate quote.</p>}
          {bookings.length > 0 && <div className="historical-notice"><b>Central booking requests</b><span>{bookings.length} request(s) are on file. They have no verified payable amounts; only expense values you enter below are included in this estimate.</span></div>}
          <div className="budget-expense-fields">
            {expenseItems.map(([key, label]) => <label className="customer-input" key={key}><span>{label} ({currency})</span><input type="number" min="0" step="0.01" value={expenses[key]} onChange={(event) => updateExpense(key, event.target.value)} placeholder="Enter your estimate" /></label>)}
          </div>
          {availableBookingEstimates.length > 0 && <fieldset className="trip-interest-picker"><legend>Include customer-entered booking estimates · {currency}</legend><div>{availableBookingEstimates.map((booking) => <label key={booking.reference}><input type="checkbox" checked={estimateReferences.includes(booking.reference)} onChange={() => setEstimateReferences((current) => current.includes(booking.reference) ? current.filter((reference) => reference !== booking.reference) : [...current, booking.reference])} />{booking.bookingType} · {booking.reference} · {booking.destination || "Destination not recorded"} · {number(booking.priceBreakdown.customerEstimate, 2)} {currency}</label>)}</div><p className="data-limitation">Only your own entered estimates in this currency are selectable. Clear matching manual expense fields to avoid counting the same expense twice.</p></fieldset>}
          <button className="customer-button" onClick={saveEstimate} disabled={!hasExpenses || !destination || !validDays || !validTravellers}>Save estimate to My Trips</button>
        </section>
        <section className="customer-content-card budget-summary">
          <p className="customer-eyebrow">YOUR ESTIMATE · {currency}</p>
          <h2>{hasExpenses ? total.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "Enter estimates"}</h2>
          <p>Entered trip expenses · {number(travellers)} traveller(s)</p>
          <div className="budget-breakdown">
            {expenseItems.map(([key, label]) => <div key={key}><span>{label}</span><b>{expenses[key] === "" ? "—" : `${(Number(expenses[key]) || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`}</b></div>)}
            {selectedBookingEstimates.map((booking) => <div key={booking.reference}><span>{booking.bookingType} request · {booking.reference}</span><b>{number(booking.priceBreakdown.customerEstimate, 2)} {currency}</b></div>)}
            <div className="budget-total"><span>Per person</span><b>{hasExpenses && perPerson !== null ? `${perPerson.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}` : !validTravellers ? "Enter valid traveller count" : "—"}</b></div>
          </div>
          <label className="customer-input"><span>Source budget tier</span><select value={tier} onChange={(event) => setTier(event.target.value)}><option value="budget">Economical · source budget</option><option value="mid_range">Standard · source mid-range</option><option value="luxury">Premium · source luxury</option></select></label>
          <div className="historical-notice"><b>Separate source range</b><span>{Array.isArray(sourceRange) && validDays && validTravellers ? `${number(sourceRange[0] * Number(days) * Number(travellers))}–${number(sourceRange[1] * Number(days) * Number(travellers))} · source range × days × travellers; currency is unspecified.` : "No source range is available for this destination and tier, or enter valid trip length and travellers."}</span></div>
          <p className="data-limitation">Only expenses you enter are included in the total. Source budget ranges and historical hotel prices are kept separate from your estimate; there are no live transport or room rates.</p>
          <div className="detail-actions"><button className="customer-button subtle" onClick={() => onNavigate("transport", destination)}>Search transport</button><button className="customer-button subtle" onClick={() => onNavigate("hotels", destination)}>Search hotels</button><button className="customer-button subtle" onClick={() => onNavigate("map", destination)}>Open map</button></div>
        </section>
      </div>
    </>
  );
}

function MapsPage({ destinations, initialDestination }) {
  const [destinationId, setDestinationId] = useState(initialDestination?.id ?? destinations[0]?.id ?? "");
  const [placeType, setPlaceType] = useState("Destination");
  const [manualOrigin, setManualOrigin] = useState("");
  const [mapLocation, setMapLocation] = useState(
    initialDestination
      ? initialDestination.coordinates_latitude != null && initialDestination.coordinates_longitude != null
        ? `${initialDestination.coordinates_latitude},${initialDestination.coordinates_longitude}`
        : `${initialDestination.destination_name}, ${initialDestination.state || ""}`
      : "",
  );
  const [locationNotice, setLocationNotice] = useState("");
  const [mapError, setMapError] = useState(false);
  const destination = destinations.find((item) => String(item.id) === String(destinationId));
  const sourceCenter = destination?.coordinates_latitude != null && destination?.coordinates_longitude != null
    ? `${destination.coordinates_latitude},${destination.coordinates_longitude}`
    : `${destination?.destination_name || ""}, ${destination?.state || ""}`;
  const center = mapLocation.trim() || sourceCenter;
  const mapQuery = placeType === "Destination" ? center : `${placeType} near ${center}`;
  const embedUrl = `https://maps.google.com/maps?q=${encodeURIComponent(mapQuery)}&z=13&output=embed`;
  const searchUrl = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(mapQuery)}`;
  const directionsUrl = `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(manualOrigin)}&destination=${encodeURIComponent(center)}`;
  useEffect(() => {
    if (destinations.length && !destinations.some((item) => String(item.id) === String(destinationId))) {
      setDestinationId(initialDestination?.id ?? destinations[0].id);
    }
  }, [destinations, destinationId, initialDestination]);
  useEffect(() => {
    if (destination) {
      setMapLocation(
        destination.coordinates_latitude != null && destination.coordinates_longitude != null
          ? `${destination.coordinates_latitude},${destination.coordinates_longitude}`
          : `${destination.destination_name}, ${destination.state || ""}`,
      );
    }
  }, [destinationId, destination?.destination_name, destination?.state]);
  const requestLocation = () => {
    if (!navigator.geolocation) {
      setLocationNotice("Location is unavailable in this browser. You can enter a starting place manually.");
      return;
    }
    setLocationNotice("Requesting location permission…");
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        const coordinates = `${coords.latitude.toFixed(5)}, ${coords.longitude.toFixed(5)}`;
        setManualOrigin(coordinates);
        setMapLocation(coordinates);
        setLocationNotice("Current coordinates are being used for Google Maps search and directions.");
      },
      () => setLocationNotice("Location was not shared. Enter a starting place manually."),
      { timeout: 10000 },
    );
  };
  return (
    <>
      <PageTitle eyebrow="MAPS · DESTINATION CONTEXT" title="Find your way around." description="Explore a destination and nearby places in Google Maps. Current-location access is optional." />
      <div className="browse-tools map-controls">
        <label className="customer-input"><span>Destination</span><select value={destinationId} onChange={(event) => setDestinationId(event.target.value)}>{destinations.map((item) => <option key={item.id} value={item.id}>{item.destination_name} · {item.state}</option>)}</select></label>
        <label className="customer-input"><span>Search location or current coordinates</span><input value={mapLocation} onChange={(event) => setMapLocation(event.target.value)} placeholder="Enter a destination, address or coordinates" /></label>
        <label className="customer-input"><span>Nearby place type</span><select value={placeType} onChange={(event) => setPlaceType(event.target.value)}>{["Destination", "Hotels", "Bus stations", "Railway stations", "Transit stops", "Airports", "Taxi services", "Car rental", "Bike rental", "Scooter rental", "Tourist attractions", "Restaurants"].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label className="customer-input"><span>Starting location for directions</span><input value={manualOrigin} onChange={(event) => setManualOrigin(event.target.value)} placeholder="Enter a place or coordinates" /></label>
        <button className="customer-button subtle" type="button" onClick={requestLocation}>Use my location</button>
      </div>
      {locationNotice && <p className="data-limitation" role="status">{locationNotice}</p>}
      {mapError && <p className="customer-error" role="status">The embedded map could not be loaded. Use the external Google Maps search or directions links below.</p>}
      <div className="map-frame"><iframe title={`Google Maps: ${mapQuery}`} src={embedUrl} loading="lazy" referrerPolicy="no-referrer-when-downgrade" onError={() => setMapError(true)} /></div>
      <div className="detail-actions map-actions"><a className="customer-button" href={searchUrl} target="_blank" rel="noreferrer">Open search in Google Maps</a>{manualOrigin && <a className="customer-button subtle" href={directionsUrl} target="_blank" rel="noreferrer">Get directions</a>}</div>
      <div className="historical-notice"><b>External map search</b><span>Nearby hotels, stations, rentals and attractions are Google Maps search results, not TravelIntel-verified locations, providers, schedules, availability or prices.</span></div>
      {list(destination?.primary_attractions).length > 0 && <section className="customer-content-card map-attractions"><h2>Attractions listed in TravelIntel data</h2><p className="data-limitation">These are destination source attributes, not verified live map pins.</p><div className="map-attraction-list">{list(destination.primary_attractions).map((attraction) => <a key={attraction} href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${attraction}, ${destination.destination_name}`)}`} target="_blank" rel="noreferrer">{attraction} ↗</a>)}</div></section>}
      <p className="data-limitation">No Google Maps API key is configured in the customer frontend. This uses Google Maps embed/search/directions links; live in-app Places data and route calculations depend on Google's own service availability. Hotel, transit, restaurant and rental pins are Google Maps search results, not TravelIntel inventory.</p>
    </>
  );
}

function TravelReport({ user, bookings, savedTrips, email }) {
  const reportEmail = email || user.email || "";
  const userBookings = bookings.filter((item) => item.email === reportEmail.trim().toLowerCase());
  const entries = [
    ...userBookings.map((item) => ({ id: `request:${item.reference}`, kind: "request", value: item })),
    ...savedTrips.map((item, index) => ({ id: `trip:${item.savedAt || index}`, kind: "trip", value: item })),
  ];
  const [selectedId, setSelectedId] = useState(entries[0]?.id || "");
  const selected = entries.find((entry) => entry.id === selectedId) || entries[0];
  const plan = selected?.value;
  const request = selected?.kind === "request" ? plan : null;
  const selection = request?.requestDetails;
  const budget = plan?.expenses;
  const itinerary = selection?.itinerary || plan?.itinerary || [];
  const downloadHtml = () => {
    const report = document.querySelector(".report-sheet");
    if (!report) return;
    const label = (request?.reference || plan?.destinationName || "trip-report")
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "") || "trip-report";
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>TravelIntel report</title><style>body{max-width:900px;margin:36px auto;padding:0 24px;color:#243b4a;font:16px/1.6 Arial,sans-serif}h2{font-size:26px}h3{margin-top:24px}article{border:1px solid #dfe7ea;padding:24px}div{margin:8px 0}span{overflow-wrap:anywhere}</style></head><body>${report.outerHTML}</body></html>`;
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `travelintel-${label}-report.html`;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <section className="travel-report">
      <PageTitle eyebrow="TRAVEL REPORT · PRINT / SAVE AS PDF" title="Your trip, in one report." description="Generate a print-friendly report from your saved plan or planning request. No sample bookings are inserted." />
      {entries.length > 0 ? (
        <>
          <label className="customer-input report-picker"><span>Choose saved trip or request</span><select value={selected?.id || ""} onChange={(event) => setSelectedId(event.target.value)}>{entries.map((entry) => <option key={entry.id} value={entry.id}>{entry.kind === "request" ? `Request ${entry.value.reference}` : entry.value.destinationName || "Saved trip draft"}</option>)}</select></label>
          <article className="customer-content-card report-sheet">
            <p className="customer-eyebrow">TRAVELINTEL · CUSTOMER TRAVEL REPORT</p>
            <h2>{selection?.name || plan?.destinationName || "Trip plan"}</h2>
            <p>Prepared for {request?.customerName || user.name} · {request?.email || user.email}</p>
            <div className="report-facts">
              <div><b>Destination</b><span>{selection?.location || plan?.destinationName || "Not recorded"}</span></div>
              <div><b>Origin</b><span>{request?.origin || selection?.origin || "Not recorded"}</span></div>
              <div><b>Travel date</b><span>{request?.travelDate || "Not set in saved draft"}</span></div>
              <div><b>Return date</b><span>{request?.returnDate || "Not recorded"}</span></div>
              <div><b>Travellers</b><span>{number(request?.passengerDetails?.passengers || plan?.travellers)}</span></div>
              <div><b>Booking category</b><span>{request?.bookingType || "Trip draft"}</span></div>
              <div><b>Planning reference</b><span>{request?.reference || "Saved trip draft"}</span></div>
              <div><b>Request status</b><span>{request?.bookingStatus || "Draft · not booked"}</span></div>
              <div><b>Payment</b><span>{request?.paymentStatus || "not_processed"}</span></div>
            </div>
            <h3>Itinerary</h3>
            {itinerary.length ? <ol>{itinerary.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ol> : <p>No itinerary details were saved with this plan.</p>}
            <h3>Transport, stay and rental requests</h3>
            {userBookings.length ? <div className="report-facts">{userBookings.map((booking) => {
              const details = booking.requestDetails || {};
              const passengerDetails = booking.passengerDetails || {};
              const amount = booking.priceBreakdown?.actualTotal;
              const estimate = booking.priceBreakdown?.customerEstimate;
              return <div key={booking.reference}><b>{booking.bookingType} · {booking.reference}</b><span>{booking.origin || "Origin unavailable"} → {booking.destination || "Destination unavailable"} · {booking.travelDate}{booking.returnDate ? ` to ${booking.returnDate}` : ""} · {passengerDetails.passengers ?? "—"} passenger(s){passengerDetails.rooms ? ` · ${passengerDetails.rooms} room(s)` : ""} · payment {booking.paymentStatus} · status {booking.bookingStatus} · actual total {amount == null ? "unavailable" : `${amount} ${booking.priceBreakdown?.currency || ""}`} · your estimate {estimate == null ? "not provided" : `${number(estimate, 2)} ${booking.priceBreakdown?.currency || ""}`}{details.hotel?.roomType ? ` · ${details.hotel.roomType}` : ""}{details.hotel?.amenities?.length ? ` · amenities ${details.hotel.amenities.join(", ")}` : ""}</span></div>;
            })}</div> : <p>No central booking requests are saved for this customer.</p>}
            {selection?.hotel && <p>Selected historical stay: {selection.name} · {selection.hotel.roomType || "Room type not recorded"} · {number(selection.hotel.guests)} guest(s), {number(selection.hotel.rooms)} room(s) · {selection.hotel.checkIn || "check-in not set"} to {selection.hotel.checkOut || "check-out not set"} · historical rate {selection.hotel.historicalPrice || "not in source"}.</p>}
            <h3>Expense estimate</h3>
            {budget ? <div className="report-facts">{Object.entries(budget).map(([key, value]) => <div key={key}><b>{key.replaceAll("_", " ")}</b><span>{number(value, 2)} {plan.budgetCurrency || ""}</span></div>)}{(plan.bookingEstimates || []).map((estimate) => <div key={estimate.reference}><b>Booking estimate · {estimate.reference}</b><span>{number(estimate.amount, 2)} {estimate.currency} · customer-entered</span></div>)}<div><b>Total estimate</b><span>{number(plan.totalEstimate, 2)} {plan.budgetCurrency || ""} · includes only entered estimates</span></div></div> : <p>{selection?.detail || "No expense breakdown was saved. No booking prices or payment totals are available."}</p>}
            {Array.isArray(selection?.budgetRange) && <p>Source budget range for this trip: {number(selection.budgetRange[0])}–{number(selection.budgetRange[1])} · currency not specified.</p>}
            <p className="data-limitation">This report reflects saved planning data only. It is not a ticket, hotel voucher, payment receipt, or confirmed reservation.</p>
          </article>
          <div className="detail-actions"><button className="customer-button report-print-button" onClick={downloadHtml}>Download report (.html)</button><button className="customer-button subtle report-print-button" onClick={() => window.print()}>Print / save as PDF</button></div>
          <small className="data-limitation">The HTML report downloads directly. Use Print / save as PDF to create a PDF in your browser’s print dialog.</small>
        </>
      ) : <div className="customer-empty-card"><h3>No saved trip data to report.</h3><p>Save a trip draft or planning request first. The report will use that actual saved data.</p></div>}
    </section>
  );
}

function WeatherPage({ weather, loading, error, city, setCity }) {
  const rows = weather?.monthly_averages ?? [];
  const maxPrecip = Math.max(1, ...rows.map((row) => Number(row.average_precip_mm) || 0));
  return (
    <>
      <PageTitle eyebrow="WEATHERWISE · HISTORICAL PATTERNS" title="Choose your season with context." description="Compare historical monthly weather summaries from the project’s eight city datasets. This is not a forecast and is not joined to destination profiles." />
      <div className="weather-toolbar"><label className="customer-input"><span>Weather dataset location</span><select value={city} onChange={(event) => setCity(event.target.value)}>{WEATHER_CITIES.map((item) => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}</select></label>{weather?.date_range && <span>History available: {weather.date_range[0]?.slice(0, 4)}–{weather.date_range[1]?.slice(0, 4)}</span>}</div>
      <div className="historical-notice"><b>Historical only</b><span>Monthly averages are computed from recorded weather observations between the source date range shown. They do not predict upcoming conditions.</span></div>
      {error && <div className="customer-error">{error}</div>}
      {loading ? <div className="customer-message">Calculating historical averages…</div> : rows.length ? <><div className="weather-summary-grid">{rows.map((row) => <article key={row.month}><span>{new Date(2020, Number(row.month) - 1).toLocaleString(undefined, { month: "short" })}</span><div className="weather-range"><b>{number(row.average_min_c, 1)}°</b><i>–</i><b>{number(row.average_max_c, 1)}°C</b></div><div className="weather-rain" title={`${number(row.average_precip_mm, 1)} mm average precipitation`}><i style={{ height: `${Math.max(3, (Number(row.average_precip_mm) / maxPrecip) * 55)}px` }} /></div><small>{number(row.average_precip_mm, 1)} mm avg rain</small><small>{number(row.observations)} hourly records</small></article>)}</div><div className="weather-data-note"><b>How to read this</b><span>Temperature and rainfall are averages by calendar month across all available historical years. Averages can hide short-term extremes.</span></div></> : <div className="customer-message">Weather summary not available for this location.</div>}
    </>
  );
}

function ReviewsPage({ reviews, loading, error }) {
  const summary = reviews?.tourism_reviews;
  const ratingRows = reviews?.rating_bands ?? [];
  const maxReviews = Math.max(1, ...ratingRows.map((row) => Number(row.records) || 0));
  return (
    <>
      <PageTitle eyebrow="REVIEW INTELLIGENCE · VERIFIED SIGNALS" title="What travellers chose to share." description="Explore actual tourism review text and numeric ratings from the Indian place-review dataset, without claiming automated sentiment analysis." />
      {error && <div className="customer-error">{error}</div>}
      {loading ? <div className="customer-message">Summarizing actual review records…</div> : summary && <><div className="review-summary-grid"><article><span>Tourism place reviews</span><b>{number(summary.review_count)}</b><small>source records with 1–5 ratings</small></article><article><span>Average rating</span><b>{number(summary.average_rating, 2)}<small> / 5</small></b><small>numeric ratings only</small></article><article><span>Ratings 4–5</span><b>{number(summary.high_rated)}</b><small>rating band, not text sentiment</small></article><article><span>Ratings 1–2</span><b>{number(summary.low_rated)}</b><small>rating band, not text sentiment</small></article></div>
        <div className="review-content-grid"><article className="customer-content-card"><div className="customer-section-heading compact"><div><p className="customer-eyebrow">RATING DISTRIBUTION</p><h2>Actual source ratings</h2></div></div><div className="review-rating-bars">{ratingRows.map((row) => <div key={row.rating}><span>{number(row.rating)} star</span><div><i style={{ width: `${Number(row.records) / maxReviews * 100}%` }} /></div><b>{number(row.records)}</b></div>)}</div><p className="data-limitation">{reviews.analysis_note}</p></article>
          <article className="customer-content-card"><div className="customer-section-heading compact"><div><p className="customer-eyebrow">FREQUENT PLACE LABELS</p><h2>Where reviews are tagged</h2></div></div><div className="frequent-place-list">{(reviews.frequent_places ?? []).slice(0, 8).map((place) => <div key={`${place.city}-${place.place}`}><b>{place.place}</b><span>{place.city}</span><strong>{number(place.review_count)}</strong></div>)}</div></article></div>
        <section className="review-samples"><div className="customer-section-heading compact"><div><p className="customer-eyebrow">SOURCE REVIEW EXCERPTS</p><h2>Unedited review text</h2><p>Shown as supplied in the dataset; reviewer names are not displayed.</p></div></div>{(reviews.samples ?? []).map((review, index) => <article key={`${review.city}-${index}`}><div><b>{review.place || "Place not specified"}</b><span>{review.city} · {number(review.rating)} / 5</span></div><p>“{review.review}”</p></article>)}</section>
        <div className="historical-notice"><b>Data boundary</b><span>Review text and ratings are from a separate source and are not reliably linked to the destination profile dataset. No machine-learning sentiment, themes or destination-level review scores are claimed.</span></div>
        </>}
    </>
  );
}

function BookingForm({ selection, user, onCreate, onCancel }) {
  const [name, setName] = useState(() => user.name || "");
  const email = user.email;
  const [date, setDate] = useState(() => selection?.travelDate || selection?.hotel?.checkIn || "");
  const [travellers, setTravellers] = useState(selection?.travellers || selection?.hotel?.guests || 1);
  const [error, setError] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const [saving, setSaving] = useState(false);
  const [requestId] = useState(createRequestId);
  const [customerEstimate, setCustomerEstimate] = useState("");
  const [estimateCurrency, setEstimateCurrency] = useState("INR");
  const today = new Date().toISOString().slice(0, 10);
  const submit = async (event) => {
    event.preventDefault();
    setError("");
    if (!selection) { setError("Choose a trip plan before saving a request."); return; }
    if (name.trim().length < 2) { setError("Enter a name with at least two characters."); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) { setError("Enter a valid email address."); return; }
    if (!date || date < today) { setError("Choose today or a future travel date."); return; }
    if (!Number.isInteger(Number(travellers)) || Number(travellers) < 1 || Number(travellers) > 20) { setError("Choose between 1 and 20 travellers."); return; }
    if (customerEstimate && (!Number.isFinite(Number(customerEstimate)) || Number(customerEstimate) < 0 || Number(customerEstimate) > 1000000000)) {
      setError("Enter a non-negative estimate up to 1,000,000,000, or leave it blank.");
      return;
    }
    setSaving(true);
    const request = {
      customerName: name.trim(),
      email: email.trim().toLowerCase(),
      requestId,
      bookingType: selection.bookingType || (selection.hotel ? "hotel" : "trip plan"),
      origin: selection.origin || selection.transport?.origin || "",
      destination: selection.location || selection.name || "",
      travelDate: date,
      returnDate: selection.hotel?.checkOut || null,
      passengerDetails: {
        leadPassenger: name.trim(),
        passengers: Number(travellers),
        rooms: selection.hotel?.rooms || null,
        roomType: selection.hotel?.roomType || null,
      },
      priceBreakdown: {
        supplierQuote: null,
        taxes: null,
        actualTotal: null,
        customerEstimate: customerEstimate !== "" ? Number(customerEstimate) : null,
        currency: customerEstimate !== "" ? estimateCurrency : null,
        historicalNightlyRate: selection.hotel?.historicalPrice || null,
        note: "No live supplier quote or payable total is available.",
      },
      requestDetails: selection,
    };
    try {
      const saved = await getJson("/api/customer/bookings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      const booking = saved.booking;
      onCreate(booking);
      setConfirmation(booking);
    } catch (cause) {
      setError(cause.message);
    } finally {
      setSaving(false);
    }
  };
  if (confirmation) return (
    <section className="booking-confirmation">
      <div className="confirmation-check">!</div>
      <p className="customer-eyebrow">TRIP REQUEST SAVED</p>
      <h1>Your planning reference is ready.</h1>
      <p>This request is saved in the central TravelIntel database. It is not a reservation, ticket, or payment.</p>
      <div className="confirmation-reference"><span>PLANNING REFERENCE</span><b>{confirmation.reference}</b></div>
      <dl>
        <div><dt>Trip</dt><dd>{confirmation.destination}</dd></div>
        <div><dt>Travel date</dt><dd>{confirmation.travel_date || confirmation.travelDate}</dd></div>
        <div><dt>Travellers</dt><dd>{number(confirmation.passengerDetails?.passengers)}</dd></div>
        <div><dt>Request status</dt><dd>{confirmation.bookingStatus}</dd></div>
        <div><dt>Payment</dt><dd>{confirmation.paymentStatus}</dd></div>
        {confirmation.priceBreakdown?.customerEstimate != null && <div><dt>Your estimate</dt><dd>{number(confirmation.priceBreakdown.customerEstimate, 2)} {confirmation.priceBreakdown.currency}</dd></div>}
      </dl>
      <button className="customer-button" onClick={onCancel}>Continue exploring</button>
    </section>
  );
  return (
    <div className="booking-layout"><div><button className="back-link" onClick={onCancel}>← Back to trip</button><PageTitle eyebrow="TRIP REQUEST · NO LIVE INVENTORY" title="Review your trip details." description="Save a planning request with traveller details. It does not book travel." />
      {selection ? <div className="booking-selected"><span className="customer-eyebrow">{selection.type || "TRIP PLAN"} · NOT A RESERVATION</span><h2>{selection.name}</h2><p>{selection.location}</p><small>{selection.detail}</small></div> : <div className="customer-message">Choose a trip plan first.</div>}
      <div className="booking-safety-note"><b>Payment pending · not processed</b><span>No payment gateway credentials or server-side payment verification are configured. Total payable remains unavailable; nothing will be marked paid or confirmed.</span></div>
    </div><form className="booking-form" onSubmit={submit}><p className="customer-eyebrow">TRAVELLER DETAILS</p><label className="customer-input"><span>Traveller name</span><input value={name} onChange={(event) => setName(event.target.value)} required minLength={2} autoComplete="name" /></label><label className="customer-input"><span>Signed-in account email</span><input type="email" value={email} readOnly required autoComplete="email" /></label><label className="customer-input"><span>Travel date</span><input type="date" min={today} value={date} onChange={(event) => setDate(event.target.value)} required /></label><label className="customer-input"><span>Passengers / guests</span><input type="number" min="1" max="20" value={travellers} onChange={(event) => setTravellers(event.target.value)} required /></label>{selection.hotel && <div className="booking-safety-note"><b>Stay details</b><span>{selection.hotel.roomType || "Room type not recorded"} · {selection.hotel.rooms} room(s) · {selection.hotel.checkIn || "Check-in date not selected"} to {selection.hotel.checkOut || "Check-out date not selected"} · historical nightly rate {selection.hotel.historicalPrice || "not in source"} (not a quote).</span></div>}<label className="customer-input"><span>Your estimated expense · optional, not a supplier quote</span><input type="number" min="0" max="1000000000" step="0.01" value={customerEstimate} onChange={(event) => setCustomerEstimate(event.target.value)} placeholder="Leave blank if unknown" /></label><label className="customer-input"><span>Estimate currency · no conversion</span><select value={estimateCurrency} onChange={(event) => setEstimateCurrency(event.target.value)}><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option></select></label>{error && <div className="customer-error" role="alert">{error}</div>}<button type="submit" className="customer-button full" disabled={!selection || saving}>{saving ? "Saving request…" : "Save planning request"}</button><small className="booking-private-note">Request status: planning_request · payment: not_processed. Your optional estimate is not a payable amount. This submits no payment and reserves no supplier inventory.</small></form></div>
  );
}

function MyBookings({ bookings, onCancelBooking, wishlistItems, onDetails, savedTrips, email, onDeleteTrip, onRemoveWish, onNavigate }) {
  const [tab, setTab] = useState("bookings");
  const currentBookings = email ? bookings.filter((item) => item.email === email.trim().toLowerCase()) : [];
  const today = new Date().toISOString().slice(0, 10);
  return (
    <>
      <PageTitle eyebrow="MY TRIPS" title="Your plans, all in one place." description="View saved trip requests, drafts and wishlist items from this browser." />
      <div className="detail-actions"><button className="customer-button subtle" onClick={() => onNavigate("budget")}>Budget planner</button><button className="customer-button subtle" onClick={() => onNavigate("map")}>Maps</button><button className="customer-button subtle" onClick={() => onNavigate("report")}>Travel report</button></div>
      <label className="customer-input booking-lookup"><span>Signed-in customer email</span><input type="email" value={email} readOnly /></label>
      <div className="saved-tabs" role="tablist">{[["bookings", "Trip requests"], ["trips", "Saved trips"], ["wishlist", "Wishlist"]].map(([id, title]) => <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "active" : ""} onClick={() => setTab(id)}>{title} <span>{id === "bookings" ? currentBookings.length : id === "trips" ? savedTrips.length : wishlistItems.length}</span></button>)}</div>
      {tab === "bookings" && (currentBookings.length ? <div className="booking-list">{currentBookings.map((item) => <article key={item.reference}><div className="booking-list-heading"><div><span>{item.bookingType || "Trip request"} · {item.travelDate}{item.returnDate ? ` to ${item.returnDate}` : ""} · {item.travelDate && item.travelDate < today ? "Past plan" : "Upcoming plan"}</span><h3>{item.destination || "Saved trip request"}</h3></div><b className={item.bookingStatus === "cancelled_request" ? "cancelled" : ""}>{item.bookingStatus || "planning_request"}</b></div><p>{item.origin || "Origin not recorded"} · {number(item.passengerDetails?.passengers)} traveller{item.passengerDetails?.passengers === 1 ? "" : "s"} · Payment: {item.paymentStatus || "Not processed"}{item.priceBreakdown?.customerEstimate != null ? ` · Your estimate: ${number(item.priceBreakdown.customerEstimate, 2)} ${item.priceBreakdown.currency}` : ""}</p><div className="booking-list-footer"><code>{item.reference}</code>{item.bookingStatus !== "cancelled_request" && <button onClick={() => onCancelBooking(item.reference)}>Cancel request</button>}</div></article>)}</div> : <div className="customer-empty-card"><span>✧</span><h3>{email ? "No saved trip requests for this email." : "Look up your trip requests."}</h3><p>{email ? "Save a planning request from the Trip Builder to see it here." : "Enter the email used on this browser to retrieve your saved requests."}</p></div>)}
      {tab === "trips" && (savedTrips.length ? <div className="saved-trip-list">{savedTrips.map((trip, index) => <article key={`${trip.savedAt}-${index}`}><div><p className="customer-eyebrow">SAVED TRIP DRAFT</p><h3>{trip.destinationName}</h3><span>{trip.days} days · {trip.travellers} travellers · {trip.mood || trip.budgetTier || "planning draft"}</span></div><button onClick={() => onDeleteTrip(index)}>Remove draft</button></article>)}</div> : <div className="customer-empty-card"><span>⌁</span><h3>Your next trip starts here.</h3><p>Save a trip draft from the Trip Builder.</p></div>)}
      {tab === "wishlist" && (wishlistItems.length ? <div className="destination-grid">{wishlistItems.map((item, index) => <article className="wishlist-card" key={item.id}><Photo index={item.id} alt={`Representative imagery for ${item.destination_name}`} /><div><h3>{item.destination_name}</h3><p>{item.region} · {item.state}</p><button className="customer-button subtle" onClick={() => onDetails(item)}>View destination</button><button className="wishlist-remove" onClick={() => onRemoveWish(item.id)}>Remove</button></div></article>)}</div> : <div className="customer-empty-card"><span>♡</span><h3>No saved destinations yet.</h3><p>Save places while you explore.</p></div>)}
      <p className="data-limitation">Requests are retrieved from the central database. They are not confirmed bookings and do not reserve travel.</p>
    </>
  );
}

export default function CustomerPortal({ onAdmin, onLogout, user }) {
  const [page, setPage] = useState("home");
  const [destinations, setDestinations] = useState([]);
  const [destinationLoading, setDestinationLoading] = useState(true);
  const [destinationError, setDestinationError] = useState("");
  const [selectedDestination, setSelectedDestination] = useState(null);
  const [search, setSearch] = useState("");
  const [compareIds, setCompareIds] = useState([]);
  const [wishlistIds, setWishlistIds] = useState(() => readStorage(STORAGE.wishlist, []));
  const [preferences, setPreferences] = useState(() => readStorage(STORAGE.preferences, {}));
  const [savedTrips, setSavedTrips] = useState(() => readStorage(STORAGE.trips, []));
  const [bookings, setBookings] = useState([]);
  const [customerEmail, setCustomerEmail] = useState(() => user.email);
  const [bookingError, setBookingError] = useState("");
  const [bookingSelection, setBookingSelection] = useState(null);
  const [hotels, setHotels] = useState([]);
  const [hotelLoading, setHotelLoading] = useState(false);
  const [hotelError, setHotelError] = useState("");
  const [hotelSearch, setHotelSearch] = useState("");
  const [hotelCity, setHotelCity] = useState("");
  const [transport, setTransport] = useState({ records: [], notice: "" });
  const [transportLoading, setTransportLoading] = useState(false);
  const [transportError, setTransportError] = useState("");
  const [reviews, setReviews] = useState(null);
  const [reviewsLoading, setReviewsLoading] = useState(false);
  const [reviewsError, setReviewsError] = useState("");
  const [weather, setWeather] = useState(null);
  const [weatherLoading, setWeatherLoading] = useState(false);
  const [weatherError, setWeatherError] = useState("");
  const [weatherCity, setWeatherCity] = useState("bengaluru");
  const [alternativeSource, setAlternativeSource] = useState(null);

  useEffect(() => {
    let active = true;
    getJson(`/api/customer/bookings?email=${encodeURIComponent(user.email)}`)
      .then((result) => {
        if (active) {
          setBookings(result.bookings);
          setBookingError("");
        }
      })
      .catch((error) => { if (active) setBookingError(error.message); });
    return () => { active = false; };
  }, [user.email]);

  useEffect(() => {
    let active = true;
    getJson("/api/customer/destinations")
      .then((result) => { if (active) setDestinations(result.destinations); })
      .catch((error) => { if (active) setDestinationError(error.message); })
      .finally(() => { if (active) setDestinationLoading(false); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (page !== "hotels") return undefined;
    let active = true;
    const timer = window.setTimeout(() => {
      setHotelLoading(true);
      setHotelError("");
      const query = new URLSearchParams({ limit: "60", search: hotelSearch, city: hotelCity });
      getJson(`/api/customer/accommodations?${query}`)
        .then((result) => { if (active) setHotels(result.accommodations); })
        .catch((error) => { if (active) setHotelError(error.message); })
        .finally(() => { if (active) setHotelLoading(false); });
    }, 220);
    return () => { active = false; window.clearTimeout(timer); };
  }, [page, hotelSearch, hotelCity]);

  useEffect(() => {
    if (page !== "transport" || transport.records.length) return undefined;
    let active = true;
    setTransportLoading(true);
    getJson("/api/customer/transport?limit=30")
      .then((result) => { if (active) setTransport(result); })
      .catch((error) => { if (active) setTransportError(error.message); })
      .finally(() => { if (active) setTransportLoading(false); });
    return () => { active = false; };
  }, [page, transport.records.length]);

  useEffect(() => {
    if (page !== "reviews" || reviews) return undefined;
    let active = true;
    setReviewsLoading(true);
    getJson("/api/customer/reviews?limit=12")
      .then((result) => { if (active) setReviews(result); })
      .catch((error) => { if (active) setReviewsError(error.message); })
      .finally(() => { if (active) setReviewsLoading(false); });
    return () => { active = false; };
  }, [page, reviews]);

  useEffect(() => {
    if (page !== "weather") return undefined;
    let active = true;
    setWeatherLoading(true);
    setWeatherError("");
    const query = new URLSearchParams({ city: weatherCity });
    getJson(`/api/customer/weather?${query}`)
      .then((result) => { if (active) setWeather(result); })
      .catch((error) => { if (active) setWeatherError(error.message); })
      .finally(() => { if (active) setWeatherLoading(false); });
    return () => { active = false; };
  }, [page, weatherCity]);

  const navigate = (nextPage) => setPage(nextPage);
  const openTravelTool = (nextPage, destination) => {
    if (destination) setSelectedDestination(destination);
    setPage(nextPage);
  };
  const saveWishlist = (id) => {
    const next = wishlistIds.includes(id) ? wishlistIds.filter((item) => item !== id) : [...wishlistIds, id];
    setWishlistIds(next);
    writeStorage(STORAGE.wishlist, next);
  };
  const updatePreferences = (next) => {
    const merged = { ...preferences, ...next };
    setPreferences(merged);
    writeStorage(STORAGE.preferences, merged);
  };
  const addCompare = (id, slot) => {
    setCompareIds((current) => {
      if (slot !== undefined) {
        const next = ["", "", ""];
        current.slice(0, 3).forEach((item, index) => { next[index] = item; });
        next[slot] = String(id);
        for (let index = 0; index < next.length; index += 1) {
          if (next[index] && next.indexOf(next[index]) !== index) next[index] = "";
        }
        return next;
      }
      const selected = current.filter(Boolean);
      if (selected.includes(String(id))) return selected.filter((item) => item !== String(id));
      if (selected.length >= 3) return [...selected.slice(1), String(id)];
      return [...selected, String(id)];
    });
    if (slot === undefined && page !== "compare") setPage("compare");
  };
  const openTrip = (destination) => { setSelectedDestination(destination); setPage("trip"); };
  const openDetails = (destination) => { setSelectedDestination(destination); setPage("details"); };
  const openAlternatives = (destination = selectedDestination) => { setAlternativeSource(destination); setPage("alternatives"); };
  const openBooking = (selection) => { setBookingSelection(selection); setPage("booking"); };
  const saveTrip = (trip) => {
    const next = [trip, ...savedTrips];
    setSavedTrips(next);
    writeStorage(STORAGE.trips, next);
  };
  const cancelDemoRequest = async (reference) => {
    try {
      const result = await getJson(`/api/customer/bookings/${encodeURIComponent(reference)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: user.email }),
      });
      setBookings((current) => current.map((item) => item.reference === reference ? result.booking : item));
    } catch (error) {
      setBookingError(error.message);
    }
  };
  const removeTrip = (index) => {
    const next = savedTrips.filter((_, itemIndex) => itemIndex !== index);
    setSavedTrips(next);
    writeStorage(STORAGE.trips, next);
  };
  const wishlistItems = wishlistIds.map((id) => destinations.find((item) => String(item.id) === String(id))).filter(Boolean);

  return (
    <div className="customer-site">
      <CustomerHeader page={page} onNavigate={navigate} onAdmin={onAdmin} onLogout={onLogout} user={user} />
      <main className="customer-main">
        {page === "home" && <HomePage destinations={destinations} loading={destinationLoading} error={destinationError} onNavigate={navigate} onDetails={openDetails} onWishlist={saveWishlist} wishlist={wishlistIds} onTrip={openTrip} search={search} setSearch={setSearch} onCompare={(id) => addCompare(id)} />}
        {page === "discover" && <DiscoverPage destinations={destinations} loading={destinationLoading} error={destinationError} wishlist={wishlistIds} onWishlist={saveWishlist} onDetails={openDetails} onTrip={openTrip} search={search} setSearch={setSearch} compareIds={compareIds} onCompare={addCompare} onAlternatives={() => openAlternatives()} />}
        {page === "mood" && <MoodPage destinations={destinations} onDetails={openDetails} onTrip={openTrip} />}
        {page === "trip" && <TripBuilder key={selectedDestination?.id ?? "default"} destinations={destinations} initialDestination={selectedDestination} preferences={preferences} onPreferences={updatePreferences} onSaveTrip={saveTrip} onBooking={openBooking} onOpenPage={openTravelTool} />}
        {page === "compare" && <ComparePage destinations={destinations} compareIds={compareIds} onCompare={addCompare} onTrip={openTrip} onAlternatives={openAlternatives} />}
        {page === "alternatives" && <AlternativesPage destinations={destinations} selectedDestination={alternativeSource} onSelectDestination={setAlternativeSource} onDetails={openDetails} onTrip={openTrip} />}
        {page === "details" && <DestinationDetails destination={selectedDestination} index={selectedDestination?.id ?? 0} onBack={() => navigate("discover")} onWishlist={saveWishlist} saved={wishlistIds.includes(selectedDestination?.id)} onTrip={openTrip} onCompare={(id) => addCompare(id)} onAlternatives={openAlternatives} />}
        {page === "hotels" && <HotelsPage hotels={hotels} loading={hotelLoading} error={hotelError} city={hotelCity} setCity={setHotelCity} search={hotelSearch} setSearch={setHotelSearch} onSelectHotel={openBooking} />}
        {page === "transport" && <TransportPage records={transport.records} notice={transport.notice} loading={transportLoading} error={transportError} onBooking={openBooking} />}
        {page === "budget" && <BudgetPlanner destinations={destinations} initialDestination={selectedDestination} onSaveTrip={saveTrip} onNavigate={openTravelTool} bookings={bookings} />}
        {page === "map" && <MapsPage destinations={destinations} initialDestination={selectedDestination} />}
        {page === "report" && <TravelReport user={user} bookings={bookings} savedTrips={savedTrips} email={customerEmail} />}
        {page === "weather" && <WeatherPage weather={weather} loading={weatherLoading} error={weatherError} city={weatherCity} setCity={setWeatherCity} />}
        {page === "reviews" && <ReviewsPage reviews={reviews} loading={reviewsLoading} error={reviewsError} />}
        {page === "booking" && <BookingForm selection={bookingSelection} user={user} onCreate={(booking) => { setBookings((current) => [booking, ...current]); setCustomerEmail(booking.email); setBookingError(""); }} onCancel={() => navigate("home")} />}
        {page === "bookings" && <><MyBookings bookings={bookings} onCancelBooking={cancelDemoRequest} wishlistItems={wishlistItems} onDetails={openDetails} savedTrips={savedTrips} email={customerEmail} onDeleteTrip={removeTrip} onRemoveWish={saveWishlist} onNavigate={navigate} />{bookingError && <div className="customer-error" role="alert">{bookingError}</div>}</>}
      </main>
      <footer className="customer-footer">
        <button className="customer-brand" onClick={() => navigate("home")}><span className="customer-brand-mark"><i /><i /><i /></span><span>Travel<span>Intel</span><small>DISCOVER WITH INSIGHT</small></span></button>
        <p>Intelligence for a more considered journey.<br /><small>College project demonstration · historical and descriptive data only.</small></p>
        <div><button onClick={() => navigate("reviews")}>Data boundaries</button><button onClick={onAdmin}>Admin Analytics</button></div>
      </footer>
    </div>
  );
}
