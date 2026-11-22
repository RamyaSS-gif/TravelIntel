PRAGMA foreign_keys = ON;

CREATE TABLE warehouse_manifest (
    source_file TEXT PRIMARY KEY,
    output_file TEXT NOT NULL,
    table_name TEXT NOT NULL,
    attribute_table_name TEXT,
    rows_loaded INTEGER NOT NULL CHECK (rows_loaded >= 0),
    attribute_values_loaded INTEGER NOT NULL DEFAULT 0 CHECK (attribute_values_loaded >= 0),
    storage_mode TEXT NOT NULL
);

CREATE TABLE dim_date (
    date_key INTEGER PRIMARY KEY,
    date_value TEXT NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day INTEGER NOT NULL CHECK (day BETWEEN 1 AND 31),
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    weekday_name TEXT NOT NULL
);

CREATE TABLE dim_hotel_type (
    hotel_key INTEGER PRIMARY KEY,
    hotel_type TEXT NOT NULL UNIQUE
);

CREATE TABLE fact_hotel_booking (
    booking_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    date_key INTEGER NOT NULL,
    hotel_key INTEGER NOT NULL,
    is_canceled INTEGER,
    lead_time INTEGER,
    stays_in_weekend_nights INTEGER,
    stays_in_week_nights INTEGER,
    adults INTEGER,
    children REAL,
    babies INTEGER,
    previous_cancellations INTEGER,
    previous_bookings_not_canceled INTEGER,
    booking_changes INTEGER,
    days_in_waiting_list INTEGER,
    adr REAL,
    required_car_parking_spaces INTEGER,
    total_of_special_requests INTEGER,
    market_segment TEXT,
    distribution_channel TEXT,
    customer_type TEXT,
    reservation_status TEXT,
    FOREIGN KEY (source_row_id) REFERENCES stg_hotel(warehouse_source_row_id),
    FOREIGN KEY (date_key) REFERENCES dim_date(date_key),
    FOREIGN KEY (hotel_key) REFERENCES dim_hotel_type(hotel_key)
);

CREATE TABLE dim_airbnb_listing (
    listing_key INTEGER PRIMARY KEY,
    source_city TEXT NOT NULL CHECK (source_city IN ('boston', 'seattle')),
    listing_id INTEGER NOT NULL,
    name TEXT,
    neighbourhood_cleansed TEXT,
    property_type TEXT,
    room_type TEXT,
    accommodates REAL,
    bedrooms REAL,
    beds REAL,
    price TEXT,
    number_of_reviews INTEGER,
    review_scores_rating REAL,
    boston_source_row_id INTEGER,
    seattle_source_row_id INTEGER,
    UNIQUE (source_city, listing_id),
    CHECK (
        (source_city = 'boston' AND boston_source_row_id IS NOT NULL AND seattle_source_row_id IS NULL)
        OR
        (source_city = 'seattle' AND seattle_source_row_id IS NOT NULL AND boston_source_row_id IS NULL)
    ),
    FOREIGN KEY (boston_source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_listings(warehouse_source_row_id),
    FOREIGN KEY (seattle_source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_listings(warehouse_source_row_id)
);

CREATE TABLE fact_airbnb_calendar_boston (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
);

CREATE TABLE fact_airbnb_calendar_seattle (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
);

CREATE TABLE fact_airbnb_review_boston (
    review_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    source_review_id INTEGER,
    reviewer_id INTEGER,
    reviewer_name TEXT,
    comments TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_reviews(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
);

CREATE TABLE fact_airbnb_review_seattle (
    review_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    source_review_id INTEGER,
    reviewer_id INTEGER,
    reviewer_name TEXT,
    comments TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_reviews(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES dim_date(date_key)
);

CREATE TABLE dim_tourism_location (
    location_key INTEGER PRIMARY KEY,
    location_name TEXT NOT NULL UNIQUE
);

CREATE TABLE fact_tourism_observation (
    tourism_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    image_id INTEGER NOT NULL UNIQUE,
    location_key INTEGER NOT NULL,
    latitude REAL,
    longitude REAL,
    avg_rating REAL,
    review_text TEXT,
    sentiment_score REAL,
    visitor_count INTEGER,
    avg_cost REAL,
    accessibility REAL,
    safety_index REAL,
    seasonality REAL,
    popularity_index REAL,
    avg_stay_duration REAL,
    transport_score REAL,
    accommodation_score REAL,
    cultural_score REAL,
    natural_score REAL,
    infrastructure_score REAL,
    cleanliness_score REAL,
    season_peak_factor REAL,
    return_rate REAL,
    review_count INTEGER,
    attractiveness_label TEXT,
    FOREIGN KEY (source_row_id) REFERENCES stg_tourism(warehouse_source_row_id),
    FOREIGN KEY (location_key) REFERENCES dim_tourism_location(location_key)
);

CREATE INDEX idx_fact_hotel_booking_date ON fact_hotel_booking(date_key);
CREATE INDEX idx_fact_hotel_booking_hotel ON fact_hotel_booking(hotel_key);
CREATE INDEX idx_dim_airbnb_listing_source_id ON dim_airbnb_listing(source_city, listing_id);
CREATE INDEX idx_fact_airbnb_calendar_boston_date ON fact_airbnb_calendar_boston(date_key);
CREATE INDEX idx_fact_airbnb_calendar_seattle_date ON fact_airbnb_calendar_seattle(date_key);
CREATE INDEX idx_fact_airbnb_review_boston_date ON fact_airbnb_review_boston(date_key);
CREATE INDEX idx_fact_airbnb_review_seattle_date ON fact_airbnb_review_seattle(date_key);
CREATE INDEX idx_fact_tourism_location ON fact_tourism_observation(location_key);
