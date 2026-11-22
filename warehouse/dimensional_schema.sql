PRAGMA foreign_keys = ON;

CREATE TABLE star_dim_date (
    date_key INTEGER PRIMARY KEY,
    date_value TEXT NOT NULL UNIQUE,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    weekday_name TEXT NOT NULL
);

CREATE TABLE star_dim_hotel_type (
    hotel_key INTEGER PRIMARY KEY,
    hotel_type TEXT NOT NULL UNIQUE
);

CREATE TABLE star_dim_airbnb_listing (
    listing_key INTEGER PRIMARY KEY,
    source_city TEXT NOT NULL,
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
    FOREIGN KEY (boston_source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_listings(warehouse_source_row_id),
    FOREIGN KEY (seattle_source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_listings(warehouse_source_row_id)
);

CREATE TABLE star_dim_tourism_location (
    location_key INTEGER PRIMARY KEY,
    location_name TEXT NOT NULL UNIQUE
);

CREATE TABLE star_fact_hotel_booking (
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
    FOREIGN KEY (date_key) REFERENCES star_dim_date(date_key),
    FOREIGN KEY (hotel_key) REFERENCES star_dim_hotel_type(hotel_key)
);

CREATE TABLE star_fact_airbnb_calendar_boston (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES star_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES star_dim_date(date_key)
);

CREATE TABLE star_fact_airbnb_calendar_seattle (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES star_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES star_dim_date(date_key)
);

CREATE TABLE star_fact_airbnb_review_boston (
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
    FOREIGN KEY (listing_key) REFERENCES star_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES star_dim_date(date_key)
);

CREATE TABLE star_fact_airbnb_review_seattle (
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
    FOREIGN KEY (listing_key) REFERENCES star_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES star_dim_date(date_key)
);

CREATE TABLE star_fact_tourism_observation (
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
    FOREIGN KEY (location_key) REFERENCES star_dim_tourism_location(location_key)
);

CREATE TABLE snowflake_dim_calendar_month (
    month_key INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    UNIQUE (year, month)
);

CREATE TABLE snowflake_dim_date (
    date_key INTEGER PRIMARY KEY,
    date_value TEXT NOT NULL UNIQUE,
    day INTEGER NOT NULL,
    weekday INTEGER NOT NULL,
    weekday_name TEXT NOT NULL,
    month_key INTEGER NOT NULL,
    FOREIGN KEY (month_key) REFERENCES snowflake_dim_calendar_month(month_key)
);

CREATE TABLE snowflake_dim_hotel_type (
    hotel_key INTEGER PRIMARY KEY,
    hotel_type TEXT NOT NULL UNIQUE
);

CREATE TABLE snowflake_dim_airbnb_city (
    city_key INTEGER PRIMARY KEY,
    city_name TEXT NOT NULL UNIQUE
);

CREATE TABLE snowflake_dim_airbnb_neighbourhood (
    neighbourhood_key INTEGER PRIMARY KEY,
    city_key INTEGER NOT NULL,
    neighbourhood_name TEXT NOT NULL,
    UNIQUE (city_key, neighbourhood_key),
    UNIQUE (city_key, neighbourhood_name),
    FOREIGN KEY (city_key) REFERENCES snowflake_dim_airbnb_city(city_key)
);

CREATE TABLE snowflake_dim_airbnb_property_type (
    property_type_key INTEGER PRIMARY KEY,
    property_type TEXT NOT NULL UNIQUE
);

CREATE TABLE snowflake_dim_airbnb_room_type (
    room_type_key INTEGER PRIMARY KEY,
    room_type TEXT NOT NULL UNIQUE
);

CREATE TABLE snowflake_dim_airbnb_listing (
    listing_key INTEGER PRIMARY KEY,
    city_key INTEGER NOT NULL,
    listing_id INTEGER NOT NULL,
    neighbourhood_key INTEGER,
    property_type_key INTEGER,
    room_type_key INTEGER,
    name TEXT,
    accommodates REAL,
    bedrooms REAL,
    beds REAL,
    price TEXT,
    number_of_reviews INTEGER,
    review_scores_rating REAL,
    boston_source_row_id INTEGER,
    seattle_source_row_id INTEGER,
    UNIQUE (city_key, listing_id),
    FOREIGN KEY (city_key) REFERENCES snowflake_dim_airbnb_city(city_key),
    FOREIGN KEY (city_key, neighbourhood_key)
        REFERENCES snowflake_dim_airbnb_neighbourhood(city_key, neighbourhood_key),
    FOREIGN KEY (property_type_key)
        REFERENCES snowflake_dim_airbnb_property_type(property_type_key),
    FOREIGN KEY (room_type_key)
        REFERENCES snowflake_dim_airbnb_room_type(room_type_key),
    FOREIGN KEY (boston_source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_listings(warehouse_source_row_id),
    FOREIGN KEY (seattle_source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_listings(warehouse_source_row_id)
);

CREATE TABLE snowflake_dim_tourism_location (
    location_key INTEGER PRIMARY KEY,
    location_name TEXT NOT NULL UNIQUE
);

CREATE TABLE snowflake_fact_hotel_booking (
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
    FOREIGN KEY (date_key) REFERENCES snowflake_dim_date(date_key),
    FOREIGN KEY (hotel_key) REFERENCES snowflake_dim_hotel_type(hotel_key)
);

CREATE TABLE snowflake_fact_airbnb_calendar_boston (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_boston_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES snowflake_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES snowflake_dim_date(date_key)
);

CREATE TABLE snowflake_fact_airbnb_calendar_seattle (
    calendar_fact_id INTEGER PRIMARY KEY,
    source_row_id INTEGER NOT NULL UNIQUE,
    listing_key INTEGER NOT NULL,
    date_key INTEGER,
    available TEXT,
    price TEXT,
    FOREIGN KEY (source_row_id)
        REFERENCES stg_hotel_accomodation_3_seattle_airbnb_open_data_calendar(warehouse_source_row_id),
    FOREIGN KEY (listing_key) REFERENCES snowflake_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES snowflake_dim_date(date_key)
);

CREATE TABLE snowflake_fact_airbnb_review_boston (
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
    FOREIGN KEY (listing_key) REFERENCES snowflake_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES snowflake_dim_date(date_key)
);

CREATE TABLE snowflake_fact_airbnb_review_seattle (
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
    FOREIGN KEY (listing_key) REFERENCES snowflake_dim_airbnb_listing(listing_key),
    FOREIGN KEY (date_key) REFERENCES snowflake_dim_date(date_key)
);

CREATE TABLE snowflake_fact_tourism_observation (
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
    FOREIGN KEY (location_key) REFERENCES snowflake_dim_tourism_location(location_key)
);

CREATE INDEX idx_star_fact_booking_date ON star_fact_hotel_booking(date_key);
CREATE INDEX idx_star_fact_airbnb_boston_listing ON star_fact_airbnb_calendar_boston(listing_key);
CREATE INDEX idx_star_fact_airbnb_seattle_listing ON star_fact_airbnb_calendar_seattle(listing_key);
CREATE INDEX idx_snowflake_dim_neighbourhood_city
    ON snowflake_dim_airbnb_neighbourhood(city_key);
CREATE INDEX idx_snowflake_fact_booking_date
    ON snowflake_fact_hotel_booking(date_key);
CREATE INDEX idx_snowflake_fact_airbnb_boston_listing
    ON snowflake_fact_airbnb_calendar_boston(listing_key);
CREATE INDEX idx_snowflake_fact_airbnb_seattle_listing
    ON snowflake_fact_airbnb_calendar_seattle(listing_key);
