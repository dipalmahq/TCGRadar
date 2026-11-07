<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

const props = withDefaults(
  defineProps<{
    modelValue: string[];
    label: string;
    allLabel: string;
    options: { value: string; label: string }[];
    disabled?: boolean;
    allowCustom?: boolean;
  }>(),
  { disabled: false, allowCustom: false },
);
const emit = defineEmits<{ "update:modelValue": [value: string[]] }>();
const menu = ref<HTMLDetailsElement | null>(null);
const search = ref("");
const custom = ref("");
const allOptions = computed(() => [
  ...props.options,
  ...props.modelValue
    .filter((v) => !props.options.some((o) => o.value === v))
    .map((v) => ({ value: v, label: v })),
]);
const visibleOptions = computed(() =>
  allOptions.value.filter((o) =>
    o.label
      .toLocaleLowerCase("de")
      .includes(search.value.toLocaleLowerCase("de")),
  ),
);
const summary = computed(() =>
  props.modelValue.length
    ? allOptions.value
        .filter((o) => props.modelValue.includes(o.value))
        .map((o) => o.label)
        .join(", ")
    : props.allLabel,
);
function toggle(value: string) {
  if (props.disabled) return;
  emit(
    "update:modelValue",
    props.modelValue.includes(value)
      ? props.modelValue.filter((v) => v !== value)
      : [...props.modelValue, value],
  );
}
function closeOutside(event: PointerEvent) {
  if (menu.value && !menu.value.contains(event.target as Node))
    menu.value.open = false;
}
function close() {
  if (!menu.value) return;
  menu.value.open = false;
  menu.value.querySelector("summary")?.focus();
}
function addCustom() {
  const value = custom.value.trim().toUpperCase();
  if (value && !props.modelValue.includes(value))
    emit("update:modelValue", [...props.modelValue, value]);
  custom.value = "";
}
onMounted(() => document.addEventListener("pointerdown", closeOutside));
onUnmounted(() => document.removeEventListener("pointerdown", closeOutside));
</script>

<template>
  <div class="multi-filter">
    <span class="multi-label">{{ label }}</span>
    <details ref="menu" class="multi-select" @keydown.esc.stop.prevent="close">
      <summary
        :aria-label="label"
        :aria-disabled="disabled"
        :title="summary"
        @click="disabled && $event.preventDefault()"
      >
        <span>{{
          modelValue.length > 1 ? `${modelValue.length} ausgewählt` : summary
        }}</span>
        <span aria-hidden="true">⌄</span>
      </summary>
      <div class="multi-menu">
        <fieldset :disabled="disabled">
          <legend>{{ label }} auswählen</legend>
          <input
            v-if="allOptions.length > 10"
            v-model="search"
            type="search"
            :aria-label="`${label} durchsuchen`"
            placeholder="Auswahl durchsuchen …"
          />
          <button
            type="button"
            class="multi-all"
            @click="emit('update:modelValue', [])"
          >
            {{ allLabel }} · Auswahl leeren
          </button>
          <div class="multi-options">
            <label
              v-for="option in visibleOptions"
              :key="option.value"
              class="multi-option"
            >
              <input
                type="checkbox"
                :checked="modelValue.includes(option.value)"
                @change="toggle(option.value)"
              />
              <span>{{ option.label }}</span>
            </label>
            <p v-if="!visibleOptions.length" class="multi-empty">
              Keine passenden Einträge.
            </p>
          </div>
          <div v-if="allowCustom" class="multi-custom">
            <input
              v-model="custom"
              :aria-label="`${label}: eigenen Wert eingeben`"
              maxlength="100"
              placeholder="z. B. OP-17"
              @keydown.enter.prevent="addCustom"
            />
            <button type="button" @click="addCustom">Hinzufügen</button>
          </div>
          <small
            >Mehrere Werte gelten als ODER. Keine Auswahl bedeutet alle.</small
          >
        </fieldset>
      </div>
    </details>
  </div>
</template>

<style>
.multi-filter {
  min-width: 0;
  flex: 1;
}
.multi-label {
  display: block;
  color: #69765e;
  font-size: 11px;
  margin-bottom: 7px;
}
.multi-select {
  position: relative;
  width: 100%;
}
.multi-select summary {
  list-style: none;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  align-items: center;
  min-height: 35px;
  border: 1px solid #dce3d4;
  border-radius: 6px;
  padding: 8px 10px;
  background: white;
  color: #4d5d41;
  font-size: 12px;
  cursor: pointer;
}
.multi-select summary::-webkit-details-marker {
  display: none;
}
.multi-select summary > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.multi-select summary[aria-disabled="true"] {
  opacity: 0.6;
  cursor: default;
}
.multi-select[open] {
  z-index: 25;
}
.multi-select[open] summary {
  border-color: #8d9e58;
  box-shadow: 0 0 0 2px #d3ee9a44;
}
.multi-menu {
  position: absolute;
  inset: calc(100% + 6px) auto auto 0;
  min-width: min(285px, 78vw);
  width: 100%;
  background: white;
  border: 1px solid #dce3d4;
  border-radius: 9px;
  padding: 12px;
  box-shadow: 0 12px 30px #20351620;
}
.multi-menu fieldset {
  margin: 0;
  padding: 0;
  border: 0;
  min-width: 0;
}
.multi-menu legend {
  font-size: 12px;
  font-weight: 650;
  margin-bottom: 9px;
}
.multi-menu input[type="search"],
.multi-custom input {
  width: 100%;
  min-width: 0;
  padding: 8px;
  margin: 0 0 8px;
  font-size: 12px;
  border: 1px solid #dce3d4;
  border-radius: 5px;
}
.multi-all {
  width: 100%;
  text-align: left;
  color: #4a6226;
  font-size: 11px;
  padding: 8px;
  background: #f3f7e9;
  border-radius: 5px;
  margin-bottom: 6px;
}
.multi-options {
  max-height: 220px;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.multi-menu .multi-option {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  padding: 9px 5px;
  font-size: 12px;
  color: #35472c;
  cursor: pointer;
}
.multi-menu .multi-option:hover {
  background: #f5f8ee;
}
.multi-menu input[type="checkbox"] {
  width: 16px;
  height: 16px;
  margin: 0;
  accent-color: #7a9b26;
  flex-shrink: 0;
}
.multi-menu small {
  display: block;
  margin-top: 9px;
  line-height: 1.5;
  font-size: 10px;
  color: #748066;
}
.multi-custom {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 8px;
}
.multi-custom button {
  font-size: 11px;
  background: #edf4df;
  padding: 8px;
  border-radius: 5px;
}
.multi-empty {
  font-size: 12px;
  padding: 8px;
}
.selection-help {
  font-size: 11px;
  line-height: 1.6;
  color: #748066;
  margin: 0;
  align-self: center;
}
.filter-row .multi-filter:nth-last-of-type(-n + 2) .multi-menu {
  left: auto;
  right: 0;
}
@media (max-width: 800px) {
  .filter-row .multi-filter {
    flex: 1 1 calc(50% - 14px);
  }
}
@media (max-width: 480px) {
  .filter-row .multi-filter {
    flex-basis: calc(50% - 14px);
  }
  .filter-row .multi-menu {
    min-width: min(245px, 70vw);
  }
  .filter-row .multi-filter:nth-child(even) .multi-menu {
    left: auto;
    right: 0;
  }
}
</style>
