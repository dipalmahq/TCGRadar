export interface Game {
  id: number;
  slug: string;
  name: string;
  product_line: string;
}
export interface Expansion {
  id: number;
  game_id: number;
  code: string;
  name: string;
}
export interface Meta {
  games: Game[];
  sets: Expansion[];
  channels: string[];
  notifications_enabled: boolean;
  authentication_enabled: boolean;
  stale_after_minutes: number;
}
export interface Offer {
  id: number;
  product_id: number;
  title: string;
  url: string;
  game: string;
  game_name: string;
  set_code: string | null;
  language: string;
  product_type: string;
  booster_count: number | null;
  condition: string;
  match_confidence: string;
  merchant_id: number;
  merchant: string;
  country: string;
  price_minor: number | null;
  currency: string;
  price_per_booster_minor: number | null;
  shipping_minor: number | null;
  shipping_country: string | null;
  availability: string;
  observed_availability: string;
  stale: boolean;
  source_error: string | null;
  first_seen_at: string;
  last_seen_at: string;
  last_changed_at: string;
}
export interface Merchant {
  id: number;
  slug: string;
  name: string;
  base_url: string;
  country: string;
  adapter: string;
  enabled: boolean;
  interval_seconds: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  error_count: number;
  last_offer_count: number;
  last_scanned_count: number;
  next_check_at: string;
  requested_at: string | null;
  locked_until: string | null;
}
export interface Rule {
  id: number;
  name: string;
  query: string;
  game_id: number | null;
  product_id: number | null;
  merchant_id: number | null;
  set_code: string | null;
  language: string | null;
  product_type: string | null;
  max_price_minor: number | null;
  include_preorders: boolean;
  channels: string[];
  enabled: boolean;
  game_ids: number[];
  merchant_ids: number[];
  set_codes: string[];
  languages: string[];
  product_types: string[];
}
export interface Watch {
  id: number;
  merchant_id: number;
  url: string;
  max_price_minor: number | null;
  channels: string[];
  include_preorders: boolean;
  enabled: boolean;
  last_checked_at: string | null;
  last_error: string | null;
}
export interface Overview {
  offers: number;
  in_stock: number;
  preorders: number;
  new_today: number;
  rules: number;
  pending_notifications: number;
  last_success_at: string | null;
}
export interface RadarEvent {
  id: number;
  kind: string;
  title: string;
  url: string;
  merchant: string;
  created_at: string;
  current: {
    price_minor: number | null;
    currency: string;
    availability: string;
  };
}
export interface Message {
  id: number;
  channel: string;
  status: string;
  title: string;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}
export interface Activity {
  events: RadarEvent[];
  notifications: Message[];
}
export interface History {
  id: number;
  observed_at: string;
  price_minor: number | null;
  currency: string;
  availability: string;
}
