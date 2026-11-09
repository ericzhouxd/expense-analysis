/** Category colors and 8×8 pixel glyphs drawn as box-shadows. */

const NAMED: Record<string, string> = {
  food: "#9FD39B",
  "dining out": "#FF9A80",
  transportation: "#7CB8FF",
  "daily necessities": "#F2C14E",
  entertainment: "#C7A6FF",
  rent: "#7CF2E0",
  tuition: "#FFB347",
  uncategorized: "#8E9687",
};

const PALETTE = [
  "#9FD39B",
  "#FF9A80",
  "#7CB8FF",
  "#F2C14E",
  "#C7A6FF",
  "#7CF2E0",
  "#FFB347",
  "#FF7AC6",
  "#B8E986",
  "#A0C4FF",
];

export function categoryColor(name: string): string {
  const key = name.toLowerCase();
  const named = NAMED[key];
  if (named) return named;
  let hash = 0;
  for (const character of key) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length] ?? "#9FD39B";
}

const GLYPHS: Record<string, string[]> = {
  food: ["..#..#..", ".#..#...", "#......#", "########", ".######.", "..####..", "........", "........"],
  dining: ["..#.#...", ".#.#....", "######..", "#....###", "#....#.#", "#....###", ".####...", "........"],
  bus: [".######.", "#......#", "########", "#......#", "########", "#.#..#.#", ".#....#.", "........"],
  bag: ["..####..", ".#....#.", "########", "#......#", "#......#", "#......#", "########", "........"],
  ticket: ["...#....", "..###...", "########", ".######.", "..####..", ".##..##.", ".#....#.", "........"],
  house: ["...##...", "..####..", ".######.", "########", ".#....#.", ".#.##.#.", ".#.##.#.", "........"],
  cap: ["........", "...##...", ".######.", "########", ".######.", ".#....#.", ".######.", "........"],
  phone: [".####...", ".#..#...", ".#..#...", ".#..#...", ".#..#...", ".####...", ".#.##...", "........"],
  pill: ["..###...", ".#####..", ".######.", "..######", "...####.", "....##..", "........", "........"],
  shirt: [".##..##.", "########", "#.####.#", "..####..", "..####..", "..####..", "..####..", "........"],
  plane: ["...#....", "...##...", "#######.", "########", "...##...", "..####..", "...#....", "........"],
  ball: ["..####..", ".#.##.#.", "#..##..#", "########", "#..##..#", ".#.##.#.", "..####..", "........"],
  chip: [".#.#.#..", "#######.", ".#...#..", "##.#.##.", ".#...#..", "#######.", ".#.#.#..", "........"],
  bolt: ["....##..", "...##...", "..##....", ".######.", "....##..", "...##...", "..##....", "........"],
  wave: ["........", ".##..##.", "#..##..#", "........", ".##..##.", "#..##..#", "........", "........"],
  coin: ["..####..", ".#....#.", "#..##..#", "#.#..#.#", "#..##..#", ".#....#.", "..####..", "........"],
  pencil: ["......##", ".....###", "....###.", "...###..", "..###...", ".###....", "##......", "........"],
  cross: ["...##...", "...##...", ".######.", ".######.", "...##...", "...##...", "........", "........"],
  shirtWash: ["########", "#......#", "#.####.#", "#.#..#.#", "#.####.#", "#......#", "########", "........"],
  arrow: ["...#....", "...##...", "#######.", "########", "#######.", "...##...", "...#....", "........"],
};

const BY_CATEGORY: Record<string, string> = {
  food: "food",
  groceries: "food",
  "dining out": "dining",
  restaurants: "dining",
  coffee: "dining",
  transportation: "bus",
  transport: "bus",
  "daily necessities": "bag",
  shopping: "bag",
  entertainment: "ticket",
  rent: "house",
  "housing and meal plan": "house",
  housing: "house",
  tuition: "cap",
  "school fees": "cap",
  "cell phone": "phone",
  medicine: "pill",
  insurance: "cross",
  clothes: "shirt",
  flight: "plane",
  travel: "plane",
  hotel: "house",
  sports: "ball",
  tech: "chip",
  utilities: "bolt",
  internet: "wave",
  stationery: "pencil",
  laundry: "shirtWash",
  church: "cross",
  income: "arrow",
};

export function glyphRows(category: string): string[] {
  const key = BY_CATEGORY[category.toLowerCase()] ?? "coin";
  return GLYPHS[key] ?? GLYPHS.coin ?? [];
}

export function glyphShadow(category: string, color: string, pixel = 2): string {
  const shadows: string[] = [];
  glyphRows(category).forEach((row, y) => {
    [...row].forEach((cell, x) => {
      if (cell === "#") shadows.push(`${x * pixel}px ${y * pixel}px 0 0 ${color}`);
    });
  });
  return shadows.join(",");
}

export function rgba(hex: string, alpha: number): string {
  const value = parseInt(hex.replace("#", ""), 16);
  return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
}

/** Mix a color toward white: the hot core of a lit LED. */
export function hot(hex: string, amount: number): string {
  const value = parseInt(hex.replace("#", ""), 16);
  const mix = (channel: number) => Math.round(channel + (255 - channel) * amount);
  return `rgb(${mix((value >> 16) & 255)},${mix((value >> 8) & 255)},${mix(value & 255)})`;
}
