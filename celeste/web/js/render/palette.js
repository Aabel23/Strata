// Colours shared by scene (stars), edges and the edge-type legend.
export const PALETTE = ['#c98a6b', '#8fb0a3', '#9aa6c9', '#c7a0b8', '#b5c27a', '#7fb6c4', '#cfa05a', '#a79bc9', '#d19a8f', '#86b98f', '#b8b08a', '#8aa3b8'];
export const GOLD = '#d8ae70'; // nodes without a community: the study's star colour
const KNOWN = { CALLS: '#d8ae70', IMPORTS: '#7f9bc4', EXTENDS: '#c48fa0', IMPLEMENTS: '#a79bc9', DEFINES: '#8aa3b8', CONTAINS: '#8aa3b8', HAS_METHOD: '#86b98f', ACCESSES: '#c98a6b' };
const FALLBACK = ['#b5c27a', '#7fb6c4', '#cfa05a', '#d19a8f', '#b8b08a'];
export const edgeColor = (type, i) => KNOWN[type] ?? FALLBACK[i % FALLBACK.length];
