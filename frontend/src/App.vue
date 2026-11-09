<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from "vue";
import {
  Radar,
  ArrowUpRight,
  ArrowDown,
  Bell,
  BellRing,
  Search,
  SlidersHorizontal,
  Plus,
  X,
  RefreshCw,
  Store,
  Activity as ActivityIcon,
  LayoutGrid,
  ChevronLeft,
  ChevronRight,
  CircleCheck,
  CircleAlert,
  Link,
  Trash2,
  Pause,
  Play,
  ArrowRight,
  Layers,
  LogOut,
  Menu,
  Check,
  Clock3,
  ExternalLink,
  GitCompareArrows,
} from "lucide-vue-next";
import type {
  Activity,
  History,
  Merchant,
  Meta,
  Offer,
  Overview,
  Rule,
  Watch,
} from "./types";
import MultiSelect from "./MultiSelect.vue";

type Section = "radar" | "watches" | "shops" | "activity";
const section = ref<Section>("radar");
const meta = ref<Meta>({
  games: [],
  sets: [],
  channels: [],
  notifications_enabled: false,
  authentication_enabled: false,
  stale_after_minutes: 1440,
});
const overview = ref<Overview>({
  offers: 0,
  in_stock: 0,
  preorders: 0,
  new_today: 0,
  rules: 0,
  pending_notifications: 0,
  last_success_at: null,
});
const merchants = ref<Merchant[]>([]);
const offers = ref<Offer[]>([]);
const rules = ref<Rule[]>([]);
const watches = ref<Watch[]>([]);
const activity = ref<Activity>({ events: [], notifications: [] });
const total = ref(0);
const offset = ref(0);
const pageSize = 24;
const loading = ref(true);
const busy = ref(false);
const error = ref("");
const toast = ref("");
const unauthorized = ref(false);
const keyInput = ref("");
const teamKey = ref(sessionStorage.getItem("radar-team-key") || "");
const mobileMenu = ref(false);
const filtersOpen = ref(true);
const filters = reactive({
  q: "",
  game: [] as string[],
  set_code: [] as string[],
  merchant_id: [] as string[],
  language: [] as string[],
  product_type: [] as string[],
  availability: [] as string[],
  sort: "recent",
  rule_id: "",
});
const modal = ref<"rule" | "link" | null>(null);
const selectedProductId = ref<number | null>(null);
const editingRuleId = ref<number | null>(null);
const form = reactive({
  name: "",
  query: "",
  game_ids: [] as string[],
  set_codes: [] as string[],
  merchant_ids: [] as string[],
  languages: [] as string[],
  product_types: [] as string[],
  enabled: true,
  price: "",
  include_preorders: false,
  discord: true,
  telegram: false,
  url: "",
});
const detail = ref<Offer | null>(null);
const comparisons = ref<Offer[]>([]);
const history = ref<History[]>([]);
const detailLoading = ref(false);
const formError = ref("");
const searchInput = ref<HTMLInputElement | null>(null);
let previousFocus: HTMLElement | null = null;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let searchTimer: ReturnType<typeof setTimeout> | undefined;
let toastTimer: ReturnType<typeof setTimeout> | undefined;
let offersSequence = 0;
const titles: Record<Section, string> = {
  radar: "Einkaufsradar",
  watches: "Deine Beobachtungen",
  shops: "Deine Händler",
  activity: "Was sich bewegt",
};
const langs: Record<string, string> = {
  de: "Deutsch",
  en: "Englisch",
  ja: "Japanisch",
  zh: "Chinesisch",
  fr: "Französisch",
  it: "Italienisch",
  ko: "Koreanisch",
  unknown: "Unbekannt",
};
const types: Record<string, string> = {
  display: "Display",
  booster: "Booster",
  bundle: "Bundle",
  etb: "Trainer-Box",
  case: "Case",
  tin: "Tin",
  collection: "Kollektion",
  blister: "Blister",
  starter_deck: "Starterdeck",
};
const statusLabels: Record<string, string> = {
  in_stock: "Auf Lager",
  out_of_stock: "Ausverkauft",
  preorder: "Vorbestellung",
  unknown: "Unbekannt",
};
const eventLabels: Record<string, string> = {
  new: "Neu entdeckt",
  restock: "Restock",
  preorder: "Vorbestellung",
  price_drop: "Preis gesunken",
  price_increase: "Preis gestiegen",
};
const messageLabels: Record<string, string> = {
  pending: "Wartet auf Worker",
  sending: "Wird versendet",
  sent: "Zugestellt",
  failed: "Fehlgeschlagen",
  uncertain: "Zustellung unklar",
  muted: "Deaktiviert",
};
const filteredSets = computed(() =>
  meta.value.sets.filter(
    (s) =>
      !filters.game.length ||
      meta.value.games.some(
        (g) => filters.game.includes(g.slug) && g.id === s.game_id,
      ),
  ),
);
const activeFilterCount = computed(
  () =>
    Object.entries(filters).filter(
      ([k, v]) =>
        k !== "sort" &&
        k !== "game" &&
        (Array.isArray(v) ? v.length > 0 : Boolean(v)),
    ).length,
);
const healthyShops = computed(
  () =>
    merchants.value.filter((m) => m.last_success_at && !m.error_count).length,
);
const activeWatches = computed(
  () =>
    rules.value.filter((r) => r.enabled).length +
    watches.value.filter((w) => w.enabled).length,
);
const hasFilters = computed(() =>
  Object.entries(filters).some(
    ([k, v]) => k !== "sort" && (Array.isArray(v) ? v.length > 0 : Boolean(v)),
  ),
);
const merchantOptions = computed(() =>
  merchants.value.map((m) => ({ value: String(m.id), label: m.name })),
);
const gameOptions = computed(() =>
  meta.value.games.map((g) => ({ value: String(g.id), label: g.product_line })),
);
const setOptions = computed(() =>
  [...new Set(filteredSets.value.map((s) => s.code))].map((code) => ({
    value: code,
    label: code.toUpperCase(),
  })),
);
const ruleSetOptions = computed(() =>
  [
    ...new Set(
      meta.value.sets
        .filter(
          (s) =>
            !form.game_ids.length || form.game_ids.includes(String(s.game_id)),
        )
        .map((s) => s.code),
    ),
  ].map((code) => ({ value: code, label: code.toUpperCase() })),
);
function optionsOf(values: Record<string, string>) {
  return Object.entries(values).map(([value, label]) => ({ value, label }));
}
function selectionLabel(
  values: string[],
  labels: Record<string, string>,
  fallback: string,
) {
  return values.length
    ? values.map((v) => labels[v] || v).join(", ")
    : fallback;
}
function ruleSummary(rule: Rule) {
  const games = rule.game_ids.length
    ? rule.game_ids.map((id) => gameName(id)).join(", ")
    : gameName(rule.game_id);
  const kinds = rule.product_types.length
    ? rule.product_types
    : rule.product_type
      ? [rule.product_type]
      : [];
  const languages = rule.languages.length
    ? rule.languages
    : rule.language
      ? [rule.language]
      : [];
  return [
    games,
    selectionLabel(kinds, types, "Alle Produkte"),
    selectionLabel(languages, langs, "Alle Sprachen"),
  ].join(" · ");
}

function currency(value: number | null, unit = "EUR") {
  return value === null
    ? "—"
    : new Intl.NumberFormat("de-DE", {
        style: "currency",
        currency: unit,
      }).format(value / 100);
}
function date(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("de-DE", {
        dateStyle: "short",
        timeStyle: "short",
      }).format(new Date(value))
    : "Noch nicht geprüft";
}
function relative(value: string | null) {
  if (!value) return "Noch nicht geprüft";
  const minutes = Math.max(
    0,
    Math.floor((Date.now() - new Date(value).getTime()) / 60000),
  );
  return minutes < 1
    ? "gerade eben"
    : minutes < 60
      ? `vor ${minutes} Min.`
      : minutes < 1440
        ? `vor ${Math.floor(minutes / 60)} Std.`
        : `vor ${Math.floor(minutes / 1440)} Tagen`;
}
function gameShort(game: string) {
  return game === "one-piece"
    ? "OP"
    : game === "pokemon"
      ? "PK"
      : game === "dragon-ball-masters"
        ? "DBM"
        : "DB";
}
function gameClass(game: string) {
  if (game === "dragon-ball-masters") return "masters";
  return game === "one-piece"
    ? "onepiece"
    : game === "pokemon"
      ? "pokemon"
      : "dragonball";
}
function gameName(id: number | null) {
  const game = meta.value.games.find((g) => g.id === id);
  return game?.slug === "dragon-ball-fusion-world"
    ? "Dragon Ball · Fusion World"
    : game?.name || "Alle TCGs";
}
function gameLabel(game: { slug: string; name: string }) {
  return game.slug.startsWith("dragon-ball-") ? "Dragon Ball" : game.name;
}
function gameLine(slug: string) {
  return slug === "dragon-ball-fusion-world"
    ? "FW"
    : slug === "dragon-ball-masters"
      ? "Masters"
      : "";
}
function typeLabel(value: string) {
  return types[value] || "Typ unbekannt";
}
function merchantName(id: number | null) {
  return merchants.value.find((m) => m.id === id)?.name || "Alle Händler";
}
function notify(message: string) {
  toast.value = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toast.value = ""), 5500);
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch("/api" + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-Radar-Key": teamKey.value,
      ...options.headers,
    },
  });
  if (response.status === 401) {
    unauthorized.value = true;
    throw new Error("Bitte den Team-Schlüssel eingeben.");
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Die Anfrage konnte nicht verarbeitet werden.",
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}
async function loadOffers() {
  const sequence = ++offersSequence;
  const params = new URLSearchParams({
    limit: String(pageSize),
    offset: String(offset.value),
  });
  Object.entries(filters).forEach(([k, v]) => {
    if (Array.isArray(v)) v.forEach((value) => params.append(k, value));
    else if (v) params.set(k, v);
  });
  const result = await api<{ items: Offer[]; total: number }>(
    "/offers?" + params,
  );
  if (sequence === offersSequence) {
    offers.value = result.items;
    total.value = result.total;
  }
}
async function loadAll(quiet = false) {
  if (busy.value) return;
  busy.value = true;
  if (!quiet) loading.value = true;
  try {
    const [m, o, s, r, w, a] = await Promise.all([
      api<Meta>("/meta"),
      api<Overview>("/overview"),
      api<Merchant[]>("/shops"),
      api<Rule[]>("/rules"),
      api<Watch[]>("/watches"),
      api<Activity>("/activity"),
    ]);
    meta.value = m;
    overview.value = o;
    merchants.value = s;
    rules.value = r;
    watches.value = w;
    activity.value = a;
    await loadOffers();
    unauthorized.value = false;
    error.value = "";
  } catch (e) {
    if (!unauthorized.value)
      error.value =
        (e as Error).message || "Der Radar ist gerade nicht erreichbar.";
  } finally {
    loading.value = false;
    busy.value = false;
  }
}
async function login() {
  teamKey.value = keyInput.value.trim();
  sessionStorage.setItem("radar-team-key", teamKey.value);
  await loadAll();
  if (unauthorized.value)
    formError.value = "Dieser Team-Schlüssel stimmt nicht.";
}
function logout() {
  sessionStorage.removeItem("radar-team-key");
  teamKey.value = "";
  unauthorized.value = true;
  offers.value = [];
  keyInput.value = "";
}
function setGame(game: string) {
  filters.game = game ? [game] : [];
  filters.set_code = [];
  section.value = "radar";
  mobileMenu.value = false;
}
function toggleGame(game: string) {
  filters.game = filters.game.includes(game)
    ? filters.game.filter((g) => g !== game)
    : [...filters.game, game];
  const allowed = new Set(filteredSets.value.map((s) => s.code));
  filters.set_code = filters.set_code.filter((code) => allowed.has(code));
}
function resetFilters() {
  Object.assign(filters, {
    q: "",
    game: [],
    set_code: [],
    merchant_id: [],
    language: [],
    product_type: [],
    availability: [],
    sort: "recent",
    rule_id: "",
  });
}
watch(filters, () => {
  clearTimeout(searchTimer);
  offset.value = 0;
  searchTimer = setTimeout(
    () => loadOffers().catch((e) => (error.value = e.message)),
    250,
  );
});
async function page(delta: number) {
  offset.value = Math.max(0, offset.value + delta * pageSize);
  await loadOffers();
}

function openRule(offer?: Offer) {
  editingRuleId.value = null;
  if (offer?.source_error?.startsWith("Produktzuordnung")) {
    openLink();
    form.url = offer.url;
    return;
  }
  selectedProductId.value = offer?.product_id || null;
  formError.value = "";
  const selectedGame = offer
    ? meta.value.games.find((g) => g.slug === offer.game)
    : null;
  Object.assign(form, {
    name: offer ? offer.title.slice(0, 150) : "",
    query: offer ? "" : filters.q,
    game_ids: selectedGame
      ? [String(selectedGame.id)]
      : meta.value.games
          .filter((g) => filters.game.includes(g.slug))
          .map((g) => String(g.id)),
    set_codes: offer
      ? offer.set_code
        ? [offer.set_code]
        : []
      : [...filters.set_code],
    merchant_ids: offer ? [] : [...filters.merchant_id],
    languages: offer ? [offer.language] : [...filters.language],
    product_types: offer
      ? [offer.product_type]
      : filters.product_type.filter((t) => t !== "unknown"),
    enabled: true,
    price: "",
    include_preorders: false,
    discord:
      meta.value.channels.includes("discord") || !meta.value.channels.length,
    telegram:
      !meta.value.channels.includes("discord") &&
      meta.value.channels.includes("telegram"),
    url: "",
  });
  modal.value = "rule";
}
function showRule(rule: Rule) {
  resetFilters();
  filters.rule_id = String(rule.id);
  section.value = "radar";
}
function editRule(rule: Rule) {
  openRule();
  editingRuleId.value = rule.id;
  selectedProductId.value = rule.product_id;
  Object.assign(form, {
    name: rule.name,
    query: rule.query,
    game_ids: (rule.game_ids.length
      ? rule.game_ids
      : rule.game_id
        ? [rule.game_id]
        : []
    ).map(String),
    merchant_ids: (rule.merchant_ids.length
      ? rule.merchant_ids
      : rule.merchant_id
        ? [rule.merchant_id]
        : []
    ).map(String),
    set_codes: rule.set_codes.length
      ? [...rule.set_codes]
      : rule.set_code
        ? [rule.set_code]
        : [],
    languages: rule.languages.length
      ? [...rule.languages]
      : rule.language
        ? [rule.language]
        : [],
    product_types: rule.product_types.length
      ? [...rule.product_types]
      : rule.product_type
        ? [rule.product_type]
        : [],
    price:
      rule.max_price_minor === null ? "" : String(rule.max_price_minor / 100),
    include_preorders: rule.include_preorders,
    enabled: rule.enabled,
    discord: rule.channels.includes("discord"),
    telegram: rule.channels.includes("telegram"),
  });
}
function openLink() {
  formError.value = "";
  Object.assign(form, {
    url: "",
    price: "",
    include_preorders: false,
    discord: true,
    telegram: false,
  });
  modal.value = "link";
}
async function saveWatch() {
  formError.value = "";
  const price = form.price ? Math.round(Number(form.price) * 100) : null;
  if (price !== null && (!Number.isFinite(price) || price <= 0)) {
    formError.value = "Bitte eine gültige Preisgrenze eingeben.";
    return;
  }
  const channels = [
    form.discord ? "discord" : "",
    form.telegram ? "telegram" : "",
  ].filter(Boolean);
  if (!channels.length) {
    formError.value = "Bitte mindestens einen Alarmkanal wählen.";
    return;
  }
  busy.value = true;
  try {
    if (modal.value === "link") {
      await api("/watches", {
        method: "POST",
        body: JSON.stringify({
          url: form.url,
          max_price_minor: price,
          channels,
          include_preorders: form.include_preorders,
        }),
      });
    } else {
      await api(
        editingRuleId.value ? `/rules/${editingRuleId.value}` : "/rules",
        {
          method: editingRuleId.value ? "PUT" : "POST",
          body: JSON.stringify({
            name: form.name,
            query: form.query,
            game_ids: form.game_ids.map(Number),
            product_id: selectedProductId.value,
            merchant_ids: form.merchant_ids.map(Number),
            set_codes: form.set_codes,
            languages: form.languages,
            product_types: form.product_types,
            enabled: form.enabled,
            max_price_minor: price,
            channels,
            include_preorders: form.include_preorders,
          }),
        },
      );
    }
    modal.value = null;
    notify("Beobachtung gespeichert. Alarme gelten für kommende Änderungen.");
  } catch (e) {
    formError.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
  if (!formError.value) await loadAll(true);
}
async function mutate(path: string, options: RequestInit, message: string) {
  try {
    await api(path, options);
    notify(message);
    await loadAll(true);
  } catch (e) {
    notify((e as Error).message);
  }
}
function checkShop(shop: Merchant) {
  return mutate(
    `/shops/${shop.id}/check`,
    { method: "POST" },
    "Shop-Prüfung angefordert. Der Worker übernimmt den Abruf.",
  );
}
function toggleRule(rule: Rule) {
  return mutate(
    `/rules/${rule.id}`,
    { method: "PATCH", body: JSON.stringify({ enabled: !rule.enabled }) },
    rule.enabled ? "Beobachtung pausiert." : "Beobachtung aktiviert.",
  );
}
async function removeRule(rule: Rule) {
  if (confirm(`Beobachtung „${rule.name}“ löschen?`))
    await mutate(
      `/rules/${rule.id}`,
      { method: "DELETE" },
      "Beobachtung gelöscht.",
    );
}
async function removeWatch(item: Watch) {
  if (confirm("Produktlink nicht mehr überwachen?"))
    await mutate(
      `/watches/${item.id}`,
      { method: "DELETE" },
      "Produktlink entfernt.",
    );
}
function testAlarm(channel: string) {
  return mutate(
    "/notifications/test",
    { method: "POST", body: JSON.stringify({ channel }) },
    "Testalarm eingereiht. Den Zustellstatus findest du unter Aktivitäten.",
  );
}
async function openDetail(offer: Offer) {
  detail.value = offer;
  detailLoading.value = true;
  comparisons.value = [];
  history.value = [];
  try {
    const [c, h] = await Promise.all([
      api<{ items: Offer[] }>(`/products/${offer.product_id}/compare`),
      api<History[]>(`/offers/${offer.id}/history`),
    ]);
    if (detail.value?.id === offer.id) {
      comparisons.value = c.items;
      history.value = h;
    }
  } catch (e) {
    notify((e as Error).message);
  } finally {
    detailLoading.value = false;
  }
}
function closeDialog(event: KeyboardEvent) {
  if (event.key === "Escape") {
    modal.value = null;
    detail.value = null;
    mobileMenu.value = false;
  }
  if (
    event.key === "/" &&
    !modal.value &&
    !detail.value &&
    !["INPUT", "TEXTAREA", "SELECT"].includes(
      (event.target as HTMLElement)?.tagName,
    )
  ) {
    event.preventDefault();
    searchInput.value?.focus();
  }
  if (event.key === "Tab" && (modal.value || detail.value)) {
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    const elements = dialog
      ? Array.from(
          dialog.querySelectorAll<HTMLElement>(
            "button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]",
          ),
        ).filter((el) => el.offsetParent !== null)
      : [];
    const first = elements[0],
      last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }
}
watch(
  () => Boolean(modal.value || detail.value),
  async (visible) => {
    document.body.style.overflow = visible ? "hidden" : "";
    if (visible) {
      previousFocus = document.activeElement as HTMLElement | null;
      await nextTick();
      document
        .querySelector<HTMLElement>(
          '[role="dialog"] input:not(:disabled), [role="dialog"] button',
        )
        ?.focus();
    } else previousFocus?.focus();
  },
);
onMounted(() => {
  void loadAll();
  pollTimer = setInterval(() => {
    if (!unauthorized.value && !document.hidden && !modal.value)
      void loadAll(true);
  }, 15000);
  window.addEventListener("keydown", closeDialog);
});
onUnmounted(() => {
  clearInterval(pollTimer);
  clearTimeout(searchTimer);
  clearTimeout(toastTimer);
  window.removeEventListener("keydown", closeDialog);
});
</script>

<template>
  <div v-if="unauthorized" class="login-screen">
    <div class="login-orbit"><Radar :size="120" stroke-width="0.7" /></div>
    <form class="login-card" @submit.prevent="login">
      <div class="brand">
        <span class="brand-icon"
          ><img
            src="/dragon-radar.png"
            width="52"
            height="52"
            alt=""
            aria-hidden="true"
        /></span>
        <div>JoyBoyz<span>TCG RADAR</span></div>
      </div>
      <span class="eyebrow">DEIN TEAM. DEIN RADAR.</span>
      <h1>Willkommen an Bord.</h1>
      <p>Mit eurem Team-Schlüssel geht’s zu den Angeboten und Beobachtungen.</p>
      <label
        >Team-Schlüssel<input
          v-model="keyInput"
          type="password"
          autocomplete="current-password"
          required
          autofocus
          placeholder="Team-Schlüssel eingeben"
      /></label>
      <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
      <button class="button primary" :disabled="busy">
        Radar öffnen <ArrowRight :size="17" />
      </button>
    </form>
  </div>

  <div v-else class="app-shell">
    <button
      v-if="mobileMenu"
      class="sidebar-backdrop"
      aria-label="Menü schließen"
      @click="mobileMenu = false"
    ></button>
    <aside class="sidebar" :class="{ expanded: mobileMenu }">
      <a class="brand" href="#" @click.prevent="section = 'radar'"
        ><span class="brand-icon"
          ><img
            src="/dragon-radar.png"
            width="52"
            height="52"
            alt=""
            aria-hidden="true"
        /></span>
        <div>JoyBoyz<span>TCG RADAR</span></div></a
      >
      <div class="workspace-chip">
        <span class="workspace-dot"></span> Streamer Crew
        <span class="tiny-tag">PRIVAT</span>
      </div>
      <span class="nav-label">DEIN WORKSPACE</span>
      <nav aria-label="Hauptnavigation">
        <button
          :class="{ active: section === 'radar' }"
          @click="
            section = 'radar';
            mobileMenu = false;
          "
        >
          <LayoutGrid :size="18" /> Einkaufsradar
          <span class="nav-count">{{ overview.offers }}</span>
        </button>
        <button
          :class="{ active: section === 'watches' }"
          @click="
            section = 'watches';
            mobileMenu = false;
          "
        >
          <Bell :size="18" /> Beobachtungen
          <span class="nav-count">{{ activeWatches }}</span>
        </button>
        <button
          :class="{ active: section === 'shops' }"
          @click="
            section = 'shops';
            mobileMenu = false;
          "
        >
          <Store :size="18" /> Händler
        </button>
        <button
          :class="{ active: section === 'activity' }"
          @click="
            section = 'activity';
            mobileMenu = false;
          "
        >
          <ActivityIcon :size="18" /> Aktivitäten
        </button>
      </nav>
      <div class="sidebar-divider"></div>
      <span class="nav-label">DEINE TCGs</span>
      <div class="game-navigation">
        <button
          v-for="game in meta.games"
          :key="game.slug"
          :aria-label="
            game.slug === 'dragon-ball-fusion-world'
              ? 'Dragon Ball Fusion World'
              : game.name
          "
          @click="setGame(game.slug)"
        >
          <span class="game-dot" :class="gameClass(game.slug)"></span
          >{{ gameLabel(game)
          }}<span
            v-if="gameLine(game.slug)"
            class="tcg-line-tag"
            :class="{ 'masters-tag': game.slug === 'dragon-ball-masters' }"
            >{{ gameLine(game.slug) }}</span
          ><ChevronRight :size="14" />
        </button>
      </div>
      <div class="sidebar-callout">
        <img
          class="straw-hat"
          src="/straw-hat.svg"
          width="29"
          height="23"
          alt=""
          aria-hidden="true"
        /><strong>Ein guter Fund.<br />Ein besserer Stream.</strong>
        <button @click="openRule()">
          Beobachtung erstellen <Plus :size="15" />
        </button>
      </div>
      <div class="sidebar-bottom">
        <span class="avatar">JB</span>
        <div><strong>JoyBoyz Crew</strong><span>Deutschland & EU</span></div>
        <button
          v-if="meta.authentication_enabled"
          class="icon-button"
          title="Abmelden"
          @click="logout"
        >
          <LogOut :size="17" />
        </button>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <button
            class="icon-button mobile-only"
            aria-label="Menü öffnen"
            @click="mobileMenu = !mobileMenu"
          >
            <Menu :size="21" /></button
          ><span class="breadcrumb"
            >WORKSPACE <span>/</span>
            <strong>{{ titles[section] }}</strong></span
          >
        </div>
        <div class="topbar-right">
          <span class="region"><span>DE</span> Deutschland / EU</span
          ><span class="connection" :class="{ offline: Boolean(error) }"
            ><i></i>{{ error ? "Verbindung prüfen" : "Radar verbunden" }}</span
          ><button
            class="icon-button"
            aria-label="Daten aktualisieren"
            :disabled="busy"
            @click="loadAll()"
          >
            <RefreshCw :size="17" :class="{ spinning: busy }" />
          </button>
        </div>
      </header>

      <div class="page-content">
        <div v-if="error" class="error-banner" role="alert">
          <CircleAlert :size="18" /><span>{{ error }}</span
          ><button @click="loadAll()">Erneut versuchen</button>
        </div>
        <div class="page-heading">
          <div>
            <span class="eyebrow">{{
              section === "radar"
                ? "AUF DER SUCHE NACH DEINEM NÄCHSTEN FUND"
                : "ALLES FÜR DEINEN NÄCHSTEN STREAM"
            }}</span>
            <h1>{{ titles[section] }}<span class="heading-dot">.</span></h1>
            <p v-if="section === 'radar' && filters.rule_id">
              Gespeicherte Suche: {{ rules.find(r => String(r.id) === filters.rule_id)?.name }} · einschließlich derzeit nicht verfügbarer Angebote
            </p>
            <p>
              {{
                section === "radar"
                  ? "Packs, Displays und Restocks. An einem Ort für deine Crew."
                  : section === "watches"
                    ? "Deine Wunschprodukte. Deine Preisgrenzen. Dein Alarm."
                    : section === "shops"
                      ? "Hier sucht dein Radar nach neuen Angeboten."
                      : "Neue Funde, Bestandsänderungen und deine Alarme."
              }}
            </p>
          </div>
          <button
            v-if="section === 'radar' || section === 'watches'"
            class="button primary"
            @click="openRule()"
          >
            <Plus :size="17" /> Beobachtung erstellen</button
          ><button
            v-if="section === 'shops'"
            class="button secondary"
            :disabled="busy"
            @click="loadAll()"
          >
            <RefreshCw :size="16" /> Status aktualisieren
          </button>
        </div>

        <template v-if="section === 'radar'">
          <div class="metrics">
            <div class="metric">
              <span>ANGEBOTE IM RADAR <Layers :size="17" /></span>
              <div>
                {{ overview.offers.toLocaleString("de-DE")
                }}<small>über alle {{ meta.games.length }} TCGs</small>
              </div>
            </div>
            <div class="metric">
              <span>AUF LAGER <span class="metric-dot"></span></span>
              <div>
                {{ overview.in_stock.toLocaleString("de-DE")
                }}<small>laut letzter Händlerprüfung</small>
              </div>
            </div>
            <div class="metric">
              <span>NEU IN 24 STUNDEN <ArrowUpRight :size="18" /></span>
              <div>
                {{ overview.new_today.toLocaleString("de-DE")
                }}<small>frisch für dich entdeckt</small>
              </div>
            </div>
            <div class="metric">
              <span>AKTIVE BEOBACHTUNGEN <Bell :size="17" /></span>
              <div>
                {{ activeWatches }}<small>deine persönlichen Suchregeln</small>
              </div>
            </div>
          </div>

          <div class="radar-toolbar">
            <div class="game-tabs" aria-label="TCG filtern">
              <button
                :class="{ selected: !filters.game.length }"
                :aria-pressed="!filters.game.length"
                @click="setGame('')"
              >
                <Radar :size="16" /> Alle TCGs</button
              ><button
                v-for="game in meta.games"
                :key="game.slug"
                :aria-label="
                  game.slug === 'dragon-ball-fusion-world'
                    ? 'Dragon Ball Fusion World'
                    : game.name
                "
                :class="{ selected: filters.game.includes(game.slug) }"
                :aria-pressed="filters.game.includes(game.slug)"
                @click="toggleGame(game.slug)"
              >
                <span class="game-dot" :class="gameClass(game.slug)"></span
                >{{ gameLabel(game)
                }}<small
                  v-if="gameLine(game.slug)"
                  class="tcg-line-tag"
                  :class="{
                    'masters-tag': game.slug === 'dragon-ball-masters',
                  }"
                  >{{ gameLine(game.slug) }}</small
                >
              </button>
            </div>
            <span class="checked-label"
              ><Clock3 :size="13" /> Letzter Fund-Check
              {{ relative(overview.last_success_at) }}</span
            >
          </div>

          <section class="offers-panel" aria-label="Gefundene Angebote">
            <div class="search-row">
              <div class="search-input">
                <Search :size="18" /><input
                  ref="searchInput"
                  v-model="filters.q"
                  placeholder="Nach Set, Produkt oder Code suchen …"
                  aria-label="Angebote durchsuchen"
                /><button
                  v-if="filters.q"
                  class="icon-button"
                  aria-label="Suche leeren"
                  @click="filters.q = ''"
                >
                  <X :size="15" /></button
                ><kbd>/</kbd>
              </div>
              <button
                class="button filter-button"
                :class="{ selected: filtersOpen }"
                @click="filtersOpen = !filtersOpen"
              >
                <SlidersHorizontal :size="16" /> Filter
                <span v-if="activeFilterCount" class="filter-count">{{
                  activeFilterCount
                }}</span></button
              ><label class="sort-select"
                ><ArrowDown :size="15" /><select
                  v-model="filters.sort"
                  aria-label="Sortierung"
                >
                  <option value="recent">Neueste zuerst</option>
                  <option value="price_asc">Preis aufsteigend</option>
                  <option value="price_desc">Preis absteigend</option>
                  <option value="updated">Zuletzt geprüft</option>
                </select></label
              >
            </div>
            <div v-if="filtersOpen" class="filter-row">
              <MultiSelect
                v-model="filters.set_code"
                label="Set"
                all-label="Alle Sets"
                :options="setOptions"
              />
              <MultiSelect
                v-model="filters.merchant_id"
                label="Händler"
                all-label="Alle Händler"
                :options="merchantOptions"
              />
              <MultiSelect
                v-model="filters.language"
                label="Sprache"
                all-label="Alle Sprachen"
                :options="optionsOf(langs)"
              />
              <MultiSelect
                v-model="filters.product_type"
                label="Produkt"
                all-label="Alle Produkte"
                :options="optionsOf(types)"
              />
              <MultiSelect
                v-model="filters.availability"
                label="Verfügbarkeit"
                all-label="Alle Angebote"
                :options="optionsOf(statusLabels)"
              />
              <button
                v-if="hasFilters"
                class="clear-filters"
                @click="resetFilters"
              >
                <X :size="14" /> Zurücksetzen
              </button>
            </div>
            <div class="table-caption">
              <strong
                >{{ total }} Angebote<span v-if="filters.game.length">
                  ·
                  {{
                    meta.games
                      .filter((g) => filters.game.includes(g.slug))
                      .map((g) => g.name)
                      .join(", ")
                  }}</span
                ></strong
              ><span>Produktpreise</span>
            </div>
            <div class="table-head offer-grid">
              <span>PRODUKT</span><span>PREIS</span><span>VERFÜGBARKEIT</span
              ><span>HÄNDLER</span><span></span>
            </div>
            <div v-if="loading" class="empty-state">
              <Radar :size="34" class="spinning-slow" />
              <h2>Dein Radar sucht …</h2>
              <p>Die gefundenen Angebote werden geladen.</p>
            </div>
            <div v-else-if="!offers.length" class="empty-state">
              <span class="empty-icon"><Radar :size="35" /></span>
              <h2>
                {{
                  overview.offers
                    ? "Noch kein passender Treffer."
                    : "Bereit für die ersten Funde."
                }}
              </h2>
              <p>
                {{
                  overview.offers
                    ? "Passe deine Filter an oder lege eine Beobachtung für dein Wunschprodukt an."
                    : "Sobald der Worker die Händler geprüft hat, erscheinen hier echte Angebote."
                }}
              </p>
              <button
                class="button secondary"
                @click="overview.offers ? resetFilters() : (section = 'shops')"
              >
                {{
                  overview.offers
                    ? "Filter zurücksetzen"
                    : "Händlerstatus ansehen"
                }}
                <ArrowRight :size="15" />
              </button>
            </div>
            <article
              v-for="offer in offers"
              v-else
              :key="offer.id"
              class="offer-grid offer-row"
            >
              <div class="product-cell">
                <button
                  class="pack-art"
                  :class="gameClass(offer.game)"
                  aria-label="Produktdetails öffnen"
                  @click="openDetail(offer)"
                >
                  <span class="pack-shine"></span
                  ><span class="pack-code">{{ gameShort(offer.game) }}</span
                  ><span class="pack-lines"></span
                  ><span class="pack-set">{{ offer.set_code || "TCG" }}</span>
                </button>
                <div class="product-info">
                  <div class="product-eyebrow">
                    <span :class="gameClass(offer.game)"
                      >{{ offer.game_name
                      }}{{
                        offer.game === "dragon-ball-fusion-world"
                          ? " · Fusion World"
                          : ""
                      }}</span
                    ><span
                      v-if="
                        Date.now() - new Date(offer.first_seen_at).getTime() <
                        86400000
                      "
                      class="new-badge"
                      >NEU</span
                    >
                  </div>
                  <button class="product-title" @click="openDetail(offer)">
                    {{ offer.title }}
                  </button>
                  <div class="product-tags">
                    <span>{{ langs[offer.language] || offer.language }}</span
                    ><span>{{ typeLabel(offer.product_type) }}</span
                    ><span v-if="offer.booster_count"
                      >{{ offer.booster_count }} Booster</span
                    ><span v-if="offer.condition !== 'sealed'"
                      >OVP beschädigt</span
                    >
                  </div>
                </div>
              </div>
              <div class="price-cell">
                <strong>{{
                  currency(offer.price_minor, offer.currency)
                }}</strong
                ><span v-if="offer.price_per_booster_minor !== null"
                  >{{
                    currency(offer.price_per_booster_minor, offer.currency)
                  }}
                  / Booster</span
                ><span v-else>Packanzahl unbekannt</span
                >
              </div>
              <div class="availability-cell">
                <span class="status-badge" :class="offer.availability"
                  ><i></i>{{ statusLabels[offer.availability] }}</span>
                <small :title="date(offer.last_seen_at)">{{
                  offer.stale
                    ? "Prüfung älter als " + Math.round(meta.stale_after_minutes / 60) + " Stunden · " + relative(offer.last_seen_at)
                    : "Bestätigt " + relative(offer.last_seen_at)
                }}</small>
              </div>
              <div class="merchant-cell">
                <span>{{ offer.merchant }}</span
                ><small>{{
                  offer.country === "DE" ? "Deutschland" : offer.country
                }}</small>
              </div>
              <div class="offer-actions">
                <button
                  class="icon-button watch-button"
                  title="Produkt beobachten"
                  aria-label="Produkt beobachten"
                  @click="openRule(offer)"
                >
                  <Bell :size="17" /></button
                ><a
                  class="shop-link"
                  :href="offer.url"
                  target="_blank"
                  rel="noopener noreferrer"
                  title="Angebot beim Händler öffnen"
                  aria-label="Angebot beim Händler öffnen"
                  ><ArrowUpRight :size="20"
                /></a>
              </div>
            </article>
            <footer class="table-footer">
              <span
                >{{ total ? offset + 1 : 0 }}–{{
                  Math.min(offset + pageSize, total)
                }}
                von {{ total }} Angeboten</span
              >
              <div>
                <button
                  class="icon-button"
                  aria-label="Vorherige Seite"
                  :disabled="offset === 0"
                  @click="page(-1)"
                >
                  <ChevronLeft :size="17" /></button
                ><span>{{ Math.floor(offset / pageSize) + 1 }}</span
                ><button
                  class="icon-button"
                  aria-label="Nächste Seite"
                  :disabled="offset + pageSize >= total"
                  @click="page(1)"
                >
                  <ChevronRight :size="17" />
                </button>
              </div>
            </footer>
          </section>
          <div class="below-panel">
            <span
              ><CircleCheck :size="14" /> {{ healthyShops }} von
              {{ merchants.length }} Händlern erfolgreich geprüft</span
            ><span
              >Bestand und Endpreis werden beim Händler bestätigt.</span
            >
          </div>
        </template>

        <template v-if="section === 'watches'">
          <div
            v-if="!meta.notifications_enabled || !meta.channels.length"
            class="notice"
          >
            <Bell :size="19" />
            <div>
              <strong
                >Beobachtungen speichern, Alarme später aktivieren.</strong
              >
              <p>
                Discord oder Telegram muss vom Betreiber eingerichtet und
                aktiviert werden. Deine Regeln bleiben gespeichert.
              </p>
            </div>
          </div>
          <div class="section-heading">
            <div>
              <h2>
                Suchregeln <span class="number-pill">{{ rules.length }}</span>
              </h2>
              <p>
                Finde neue Angebote und erfahre von Restocks oder
                Preissenkungen.
              </p>
            </div>
            <button class="button secondary" @click="openLink()">
              <Link :size="15" /> Produktlink hinzufügen
            </button>
          </div>
          <div v-if="!rules.length" class="empty-state surface">
            <BellRing :size="33" />
            <h2>Deine Wunschliste wartet.</h2>
            <p>
              Wähle ein Set oder ein Produkt und lege deine Preisgrenze fest.
            </p>
            <button class="button primary" @click="openRule()">
              <Plus :size="16" /> Erste Beobachtung erstellen
            </button>
          </div>
          <div class="rules-grid">
            <article
              v-for="rule in rules"
              :key="rule.id"
              class="rule-card"
              :class="{ paused: !rule.enabled }"
            >
              <div class="rule-card-top">
                <span class="rule-icon"><Bell :size="20" /></span
                ><span
                  class="status-badge"
                  :class="rule.enabled ? 'in_stock' : 'unknown'"
                  ><i></i>{{ rule.enabled ? "Aktiv" : "Pausiert" }}</span
                >
              </div>
              <h3>{{ rule.name }}</h3>
              <p>
                {{ ruleSummary(rule) }}
              </p>
              <div class="rule-price">
                <span>DEINE PREISGRENZE</span
                ><strong>{{
                  rule.max_price_minor
                    ? currency(rule.max_price_minor)
                    : "Ohne Limit"
                }}</strong
                ><small>Preisgrenze je Artikel</small>
              </div>
              <div class="rule-meta">
                <span>{{
                  rule.query
                    ? "Suche: " + rule.query
                    : rule.product_id
                      ? "Exaktes Produkt"
                      : "Alle passenden Angebote"
                }}</span
                ><span
                  >{{ rule.channels.join(" + ")
                  }}{{
                    rule.include_preorders ? " · inkl. Vorbestellungen" : ""
                  }}</span
                >
              </div>
              <div class="rule-card-bottom">
                <span>{{
                  rule.set_codes.join(", ") ||
                  rule.set_code ||
                  (rule.merchant_ids.length
                    ? rule.merchant_ids.map(merchantName).join(", ")
                    : merchantName(rule.merchant_id))
                }}</span>
                <div>
                  <button
                    class="icon-button"
                    :aria-label="`Treffer für ${rule.name} anzeigen`"
                    title="Treffer anzeigen"
                    @click="showRule(rule)"
                  >
                    <Search :size="16" />
                  </button>
                  <button
                    class="icon-button"
                    :aria-label="`${rule.name} bearbeiten`"
                    title="Beobachtung bearbeiten"
                    @click="editRule(rule)"
                  >
                    <SlidersHorizontal :size="16" />
                  </button>
                  <button
                    class="icon-button"
                    :title="rule.enabled ? 'Pausieren' : 'Aktivieren'"
                    @click="toggleRule(rule)"
                  >
                    <Pause v-if="rule.enabled" :size="16" /><Play
                      v-else
                      :size="16"
                    /></button
                  ><button
                    class="icon-button danger"
                    title="Beobachtung löschen"
                    @click="removeRule(rule)"
                  >
                    <Trash2 :size="16" />
                  </button>
                </div>
              </div>
            </article>
          </div>
          <div class="section-heading space-top">
            <div>
              <h2>
                Direkte Produktlinks
                <span class="number-pill">{{ watches.length }}</span>
              </h2>
              <p>
                Diese Produkte werden auch außerhalb der Katalogsuche geprüft.
              </p>
            </div>
          </div>
          <div v-if="!watches.length" class="quiet-empty">
            Noch keine direkten Produktlinks hinterlegt.
          </div>
          <article
            v-for="item in watches"
            :key="item.id"
            class="watch-row surface"
          >
            <Link :size="20" />
            <div>
              <strong>{{ merchantName(item.merchant_id) }}</strong
              ><a :href="item.url" target="_blank" rel="noopener noreferrer"
                >{{ item.url }} <ArrowUpRight :size="13" /></a
              ><small :class="{ 'text-danger': item.last_error }">{{
                item.last_error ||
                "Zuletzt geprüft: " + relative(item.last_checked_at)
              }}</small>
              <small v-if="item.next_check_at" :title="date(item.next_check_at)">
                {{ new Date(item.next_check_at).getTime() < Date.now() - 60000 ? 'Prüfung überfällig seit: ' : 'Nächste Prüfung: ' }}{{ date(item.next_check_at) }}
              </small>
            </div>
            <strong>{{
              item.max_price_minor
                ? currency(item.max_price_minor)
                : "Ohne Limit"
            }}</strong
            ><button
              class="icon-button danger"
              aria-label="Produktlink entfernen"
              @click="removeWatch(item)"
            >
              <Trash2 :size="17" />
            </button>
          </article>
          <div class="section-heading space-top">
            <div>
              <h2>Alarmkanäle testen</h2>
              <p>Der Zustellstatus erscheint unter Aktivitäten.</p>
            </div>
          </div>
          <div class="channel-grid">
            <div
              v-for="channel in ['discord', 'telegram']"
              :key="channel"
              class="channel-card surface"
            >
              <span class="channel-letter">{{
                channel === "discord" ? "D" : "T"
              }}</span>
              <div>
                <strong>{{
                  channel === "discord" ? "Discord" : "Telegram"
                }}</strong
                ><small>{{
                  meta.channels.includes(channel)
                    ? "Serverseitig eingerichtet"
                    : "Noch nicht eingerichtet"
                }}</small>
              </div>
              <button
                class="button secondary"
                :disabled="
                  !meta.channels.includes(channel) ||
                  !meta.notifications_enabled
                "
                @click="testAlarm(channel)"
              >
                Testalarm <ArrowUpRight :size="14" />
              </button>
            </div>
          </div>
        </template>

        <template v-if="section === 'shops'">
          <div class="notice">
            <Radar :size="20" />
            <div>
              <strong>Deine Händler werden automatisch geprüft.</strong>
              <p>
                Neue Produkte werden aus den öffentlichen Katalogen entdeckt.
                Direkte Produktlinks ergänzen die Suche.
              </p>
            </div>
          </div>
          <div class="shops-grid">
            <article
              v-for="shop in merchants"
              :key="shop.id"
              class="merchant-card surface"
            >
              <div class="merchant-card-top">
                <span class="merchant-logo">{{ shop.name.slice(0, 1) }}</span
                ><span
                  class="status-badge"
                  :class="
                    !shop.enabled
                      ? 'unknown'
                      : shop.error_count
                        ? 'out_of_stock'
                        : shop.last_success_at
                          ? 'in_stock'
                          : 'preorder'
                  "
                  ><i></i
                  >{{
                    !shop.enabled
                      ? "Pausiert"
                      : shop.error_count
                        ? "Abruf fehlgeschlagen"
                        : shop.last_success_at
                          ? "Verbunden"
                          : "Wartet auf ersten Check"
                  }}</span
                >
              </div>
              <h2>{{ shop.name }}</h2>
              <a
                :href="shop.base_url"
                target="_blank"
                rel="noopener noreferrer"
                class="merchant-url"
                >{{ shop.base_url.replace("https://", "") }}
                <ExternalLink :size="13"
              /></a>
              <div class="merchant-facts">
                <div>
                  <span>Letzter erfolgreicher Check</span
                  ><strong>{{ date(shop.last_success_at) }}</strong>
                </div>
                <div>
                  <span>{{ shop.catalog_progress ? "Erfasste Angebote" : "Passende Angebote im letzten Abruf" }}</span
                  ><strong>{{ shop.last_offer_count }}</strong>
                </div>
                <div v-if="shop.catalog_progress">
                    <span>Katalogdurchlauf</span>
                    <strong>{{ shop.catalog_progress.in_progress ? "Wird weiter eingelesen" : shop.catalog_progress.completed_at ? "Durchlauf beendet" : "Noch nicht gestartet" }}</strong>
                </div>
                <div v-if="shop.catalog_progress">
                  <span>Fortschritt</span>
                  <strong>{{ shop.catalog_progress.pages || 0 }} Seiten · {{ shop.catalog_progress.scanned || 0 }} Produkte geprüft</strong>
                </div>
                <div v-if="shop.catalog_progress?.unresolved">
                  <span>Ungeklärte Produktzuordnungen</span>
                  <strong>{{ shop.catalog_progress.unresolved }}</strong>
                </div>
                <div>
                  <span>Prüfintervall</span
                  ><strong
                    >{{
                      Math.round(shop.interval_seconds / 60)
                    }}
                    Minuten</strong
                  >
                </div>
                <div>
                  <span>Nächste Prüfung</span
                  ><strong>{{
                    shop.locked_until &&
                    new Date(shop.locked_until).getTime() > Date.now()
                      ? "Wird gerade geprüft …"
                      : date(shop.next_check_at)
                  }}</strong>
                </div>
              </div>
              <p
                v-if="shop.last_error"
                class="source-note"
                :class="{ 'text-danger': shop.error_count }"
              >
                {{ shop.last_error }}
              </p>
              <div class="merchant-card-bottom">
                <span><span class="game-dot pokemon"></span> DE / EU</span>
                <div>
                  <button
                    class="icon-button"
                    :title="shop.enabled ? 'Shop pausieren' : 'Shop aktivieren'"
                    @click="
                      mutate(
                        `/shops/${shop.id}`,
                        {
                          method: 'PATCH',
                          body: JSON.stringify({ enabled: !shop.enabled }),
                        },
                        'Händlerstatus gespeichert.',
                      )
                    "
                  >
                    <Pause v-if="shop.enabled" :size="16" /><Play
                      v-else
                      :size="16"
                    /></button
                  ><button
                    class="button secondary"
                    :disabled="!shop.enabled"
                    @click="checkShop(shop)"
                  >
                    <RefreshCw :size="14" /> Jetzt prüfen
                  </button>
                </div>
              </div>
            </article>
          </div>
          <div class="quiet-empty">
            Weitere Händler können über die Shop-Konfiguration ergänzt werden.
            Keine vollständige Marktabdeckung.
          </div>
        </template>

        <template v-if="section === 'activity'">
          <div class="activity-columns">
            <section class="surface activity-panel">
              <div class="section-heading">
                <h2>Im Radar passiert</h2>
                <span class="number-pill">{{ activity.events.length }}</span>
              </div>
              <div v-if="!activity.events.length" class="quiet-empty">
                Noch keine Änderungen erkannt.
              </div>
              <article
                v-for="event in activity.events"
                :key="event.id"
                class="event-row"
              >
                <span class="event-icon" :class="event.kind"
                  ><ArrowDown
                    v-if="event.kind === 'price_drop'"
                    :size="17" /><RefreshCw
                    v-else-if="event.kind === 'restock'"
                    :size="17" /><Plus v-else :size="17"
                /></span>
                <div>
                  <span class="event-type"
                    >{{ eventLabels[event.kind] }} · {{ event.merchant }}</span
                  ><a
                    :href="event.url"
                    target="_blank"
                    rel="noopener noreferrer"
                    >{{ event.title }}</a
                  ><small
                    >{{
                      currency(
                        event.current.price_minor,
                        event.current.currency,
                      )
                    }}
                    · {{ date(event.created_at) }}</small
                  >
                </div>
              </article>
            </section>
            <section class="surface activity-panel">
              <div class="section-heading">
                <h2>Deine Alarme</h2>
                <Bell :size="17" />
              </div>
              <div v-if="!activity.notifications.length" class="quiet-empty">
                Sobald eine Suchregel passt oder du einen Testalarm auslöst,
                erscheint hier der Versandstatus.
              </div>
              <article
                v-for="message in activity.notifications"
                :key="message.id"
                class="message-row"
              >
                <div>
                  <strong>{{ message.title }}</strong
                  ><small
                    >{{ message.channel }} ·
                    {{ date(message.created_at) }}</small
                  >
                </div>
                <span
                  class="status-badge"
                  :class="
                    message.status === 'sent'
                      ? 'in_stock'
                      : ['failed', 'uncertain'].includes(message.status)
                        ? 'out_of_stock'
                        : 'unknown'
                  "
                  >{{ messageLabels[message.status] || message.status }}</span
                >
                <p v-if="message.last_error">{{ message.last_error }}</p>
              </article>
            </section>
          </div>
        </template>
        <footer class="page-footer">
          <span>JOYBOYZ <b>TCG RADAR</b></span
          ><span>Für deine Crew. Für den nächsten Stream.</span
          ><span>{{
            meta.games
              .map((g) =>
                g.slug === "dragon-ball-fusion-world"
                  ? "Dragon Ball FW"
                  : g.name,
              )
              .join(" · ")
          }}</span>
        </footer>
      </div>
    </main>

    <Transition name="toast"
      ><div v-if="toast" class="toast" role="status">
        <CircleCheck :size="18" />{{ toast
        }}<button
          class="icon-button"
          aria-label="Meldung schließen"
          @click="toast = ''"
        >
          <X :size="15" />
        </button></div
    ></Transition>

    <div v-if="modal" class="modal-backdrop" @click.self="modal = null">
      <section
        class="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
      >
        <div class="modal-header">
          <span class="rule-icon"
            ><Bell v-if="modal === 'rule'" :size="21" /><Link
              v-else
              :size="21" /></span
          ><button
            class="icon-button"
            aria-label="Dialog schließen"
            @click="modal = null"
          >
            <X :size="21" />
          </button>
        </div>
        <span class="eyebrow">DEIN WUNSCHPRODUKT IM BLICK</span>
        <h2 id="modal-title">
          {{
            modal === "rule"
              ? editingRuleId
                ? "Beobachtung bearbeiten"
                : "Neue Beobachtung"
              : "Produktlink überwachen"
          }}
        </h2>
        <p class="modal-intro">
          {{
            modal === "rule"
              ? "Wir melden neue passende Angebote, Restocks und Preissenkungen."
              : "Hinterlege einen Produktlink von einem deiner angebundenen Händler."
          }}
        </p>
        <form @submit.prevent="saveWatch">
          <template v-if="modal === 'rule'"
            ><label
              >Name der Beobachtung<input
                v-model="form.name"
                required
                maxlength="150"
                placeholder="z. B. One Piece OP-17 Displays" /></label
            ><label v-if="!selectedProductId"
              >Suchbegriffe<input
                v-model="form.query"
                maxlength="200"
                placeholder="z. B. OP-17 Display"
              /><small
                >Alle eingegebenen Begriffe müssen im Produktnamen
                vorkommen.</small
              ></label
            >
            <div v-else class="notice compact">
              <Layers :size="16" /><span
                >Beobachtet dieses exakt zugeordnete Produkt bei allen
                Händlern.</span
              >
            </div>
            <div class="form-grid">
              <MultiSelect
                v-model="form.game_ids"
                label="TCG"
                all-label="Alle TCGs"
                :options="gameOptions"
                :disabled="Boolean(selectedProductId)"
              />
              <MultiSelect
                v-model="form.languages"
                label="Sprache"
                all-label="Alle Sprachen"
                :options="optionsOf(langs)"
                :disabled="Boolean(selectedProductId)"
              />
              <MultiSelect
                v-model="form.product_types"
                label="Produkttyp"
                all-label="Alle Produkte"
                :options="optionsOf(types)"
                :disabled="Boolean(selectedProductId)"
              />
              <MultiSelect
                v-model="form.merchant_ids"
                label="Händler"
                all-label="Alle Händler"
                :options="merchantOptions"
              />
              <MultiSelect
                v-model="form.set_codes"
                label="Set-Code"
                all-label="Alle Sets"
                :options="ruleSetOptions"
                :disabled="Boolean(selectedProductId)"
                allow-custom
              />
              <p class="selection-help">
                Innerhalb einer Gruppe gilt ODER, zwischen Gruppen UND.
              </p>
            </div></template
          >
          <label v-else
            >Produktlink<input
              v-model="form.url"
              type="url"
              required
              placeholder="https://…/products/…"
            /><small
              >Unterstützt:
              {{ merchants.map((m) => m.name).join(", ") }}.</small
            ></label
          >
          <label
            >Maximaler Produktpreis in EUR
            <div class="currency-input">
              <input
                v-model="form.price"
                type="number"
                min="0.01"
                max="1000000"
                step="0.01"
                placeholder="Ohne Preisgrenze"
              /><span>€</span>
            </div>
            <small>Die Preisgrenze gilt je Artikel.</small></label
          >
          <label class="checkbox-label"
            ><input v-model="form.include_preorders" type="checkbox" />
            Vorbestellungen ebenfalls melden</label
          >
          <label v-if="modal === 'rule'" class="checkbox-label"
            ><input v-model="form.enabled" type="checkbox" />Beobachtung
            aktivieren</label
          >
          <fieldset>
            <legend>Benachrichtigung über</legend>
            <label class="checkbox-label"
              ><input v-model="form.discord" type="checkbox" /> Discord
              <small v-if="!meta.channels.includes('discord')"
                >noch nicht eingerichtet</small
              ></label
            ><label class="checkbox-label"
              ><input v-model="form.telegram" type="checkbox" /> Telegram
              <small v-if="!meta.channels.includes('telegram')"
                >noch nicht eingerichtet</small
              ></label
            >
          </fieldset>
          <p v-if="formError" class="form-error" role="alert">
            {{ formError }}
          </p>
          <div class="modal-footer">
            <button
              type="button"
              class="button secondary"
              @click="modal = null"
            >
              Abbrechen</button
            ><button class="button primary" :disabled="busy">
              <Check :size="16" /> Beobachtung speichern
            </button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="detail" class="modal-backdrop" @click.self="detail = null">
      <section
        class="modal detail-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="detail-title"
      >
        <div class="modal-header">
          <span class="game-label" :class="gameClass(detail.game)">{{
            detail.game_name
          }}</span
          ><button
            class="icon-button"
            aria-label="Produktdetails schließen"
            @click="detail = null"
          >
            <X :size="21" />
          </button>
        </div>
        <h2 id="detail-title">{{ detail.title }}</h2>
        <div class="detail-tags product-tags">
          <span>{{ langs[detail.language] }}</span
          ><span>{{ typeLabel(detail.product_type) }}</span
          ><span>{{
            detail.booster_count
              ? detail.booster_count + " Booster"
              : "Boosteranzahl unbekannt"
          }}</span>
        </div>
        <div class="detail-summary">
          <div>
            <span>PRODUKTPREIS</span
            ><strong>{{ currency(detail.price_minor, detail.currency) }}</strong>
          </div>
          <span class="status-badge" :class="detail.availability"
            ><i></i>{{ statusLabels[detail.availability] }}</span
          >
        </div>
        <h3><GitCompareArrows :size="17" /> Angebote für dieses Produkt</h3>
        <p class="muted">
          {{
            detail.match_confidence === "isolated"
              ? "Die Zuordnung ist nicht sicher genug für einen automatischen Vergleich mit anderen Shops."
              : "Verglichen werden ausschließlich Produkte mit übereinstimmender Produktidentität."
          }}
        </p>
        <div v-if="detailLoading" class="quiet-empty">Lade Angebote …</div>
        <a
          v-for="item in comparisons"
          :key="item.id"
          class="comparison-row"
          :href="item.url"
          target="_blank"
          rel="noopener noreferrer"
          ><div>
            <strong>{{ item.merchant }}</strong
            ><small
              >{{ statusLabels[item.availability] }}</small
            >
          </div>
          <strong>{{ currency(item.price_minor, item.currency) }}</strong
          ><ArrowUpRight :size="18"
        /></a>
        <h3 class="space-top">
          <ActivityIcon :size="17" /> Preis- und Bestandsverlauf
        </h3>
        <div class="history-list">
          <div v-for="item in history.slice(-10).reverse()" :key="item.id">
            <span>{{ date(item.observed_at) }}</span
            ><span>{{ statusLabels[item.availability] }}</span
            ><strong>{{ currency(item.price_minor, item.currency) }}</strong>
          </div>
        </div>
        <p v-if="!history.length && !detailLoading" class="muted">
          Noch kein Verlauf vorhanden.
        </p>
        <div class="modal-footer">
          <button
            class="button secondary"
            @click="
              openRule(detail);
              detail = null;
            "
          >
            <Bell :size="16" /> Beobachten</button
          ><a
            class="button primary"
            :href="detail.url"
            target="_blank"
            rel="noopener noreferrer"
            >Zum Händler <ArrowUpRight :size="17"
          /></a>
        </div>
      </section>
    </div>
  </div>
</template>
