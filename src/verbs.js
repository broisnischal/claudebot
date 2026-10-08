// Claude Code's spinner verbs, shown while the pet "thinks".
export const VERBS = [
  "Accomplishing", "Actioning", "Actualizing", "Architecting", "Baking", "Beaming", "Beboppin'",
  "Befuddling", "Billowing", "Blanching", "Bloviating", "Boogieing", "Boondoggling", "Booping",
  "Bootstrapping", "Brewing", "Bunning", "Burrowing", "Calculating", "Canoodling",
  "Caramelizing", "Cascading", "Catapulting", "Cerebrating", "Channeling", "Choreographing",
  "Churning", "Clauding", "Coalescing", "Cogitating", "Combobulating", "Composing", "Computing",
  "Concocting", "Considering", "Contemplating", "Cooking", "Crafting", "Creating", "Crunching",
  "Crystallizing", "Cultivating", "Deciphering", "Deliberating", "Determining", "Dilly-dallying",
  "Discombobulating", "Doing", "Doodling", "Drizzling", "Ebbing", "Effecting", "Elucidating",
  "Embellishing", "Enchanting", "Envisioning", "Fermenting", "Fiddle-faddling", "Finagling",
  "Flamb\u00e9ing", "Flibbertigibbeting", "Flowing", "Flummoxing", "Fluttering", "Forging",
  "Forming", "Frolicking", "Frosting", "Gallivanting", "Galloping", "Garnishing", "Generating",
  "Gesticulating", "Germinating", "Gitifying", "Grooving", "Gusting", "Harmonizing", "Hashing",
  "Hatching", "Herding", "Honking", "Hullaballooing", "Hyperspacing", "Ideating", "Imagining",
  "Improvising", "Incubating", "Inferring", "Infusing", "Ionizing", "Jitterbugging",
  "Julienning", "Kerfuffling", "Kneading", "Leavening", "Levitating", "Lollygagging",
  "Manifesting", "Marinating", "Meandering", "Metamorphosing", "Misting", "Moonwalking",
  "Moseying", "Mulling", "Mustering", "Musing", "Nebulizing", "Nesting", "Newspapering",
  "Noodling", "Nucleating", "Orbiting", "Orchestrating", "Osmosing", "Perambulating",
  "Percolating", "Perusing", "Philosophizing", "Photosynthesizing", "Pollinating", "Pondering",
  "Pontificating", "Pouncing", "Precipitating", "Prestidigitating", "Processing", "Proofing",
  "Propagating", "Puttering", "Puzzling", "Quantumizing", "Razzle-dazzling", "Razzmatazzing",
  "Recombobulating", "Reticulating", "Roosting", "Ruminating", "Saut\u00e9ing", "Scampering",
  "Schlepping", "Scurrying", "Seasoning", "Shenaniganing", "Shimmying", "Simmering",
  "Skedaddling", "Sketching", "Slithering", "Smooshing", "Sock-hopping", "Spelunking",
  "Spinning", "Sprouting", "Stewing", "Sublimating", "Swirling", "Swooping", "Symbioting",
  "Synthesizing", "Tempering", "Thinking", "Thundering", "Tinkering", "Tomfoolering",
  "Topsy-turvying", "Transfiguring", "Transmogrifying", "Transmuting", "Twisting", "Undulating",
  "Unfurling", "Unraveling", "Vibing", "Waddling", "Wandering", "Warping", "Whatchamacalliting",
  "Whirlpooling", "Whirring", "Whisking", "Wibbling", "Working", "Wrangling", "Zesting",
  "Zigzagging",
];

// Each verb gets acted out by one of these styles; anything unlisted uses the thought bubble.
const STYLES = {
  ponder: /^(Pondering|Mulling|Musing|Ruminating|Contemplating|Considering|Deliberating|Cogitating|Cerebrating|Thinking|Puzzling|Deciphering|Inferring|Determining|Ideating|Imagining|Envisioning|Perusing)$/,
  pontificate: /^(Pontificating|Philosophizing|Bloviating|Gesticulating|Elucidating|Honking|Newspapering|Channeling)$/,
  cook: /^(Baking|Cooking|Brewing|Simmering|Stewing|Marinating|Fermenting|Caramelizing|Flamb.ing|Saut.ing|Julienning|Kneading|Leavening|Proofing|Seasoning|Garnishing|Frosting|Whisking|Zesting|Blanching|Infusing|Tempering|Drizzling|Percolating|Concocting|Bunning|Churning|Smooshing)$/,
  wizard: /^(Enchanting|Manifesting|Transmuting|Transmogrifying|Transfiguring|Prestidigitating|Razzle-dazzling|Razzmatazzing|Metamorphosing|Sublimating|Clauding|Beaming)$/,
  vibe: /^(Vibing|Grooving|Boogieing|Beboppin'|Jitterbugging|Sock-hopping|Shimmying|Choreographing|Harmonizing|Improvising|Frolicking|Canoodling|Booping)$/,
  gears: /^(Computing|Calculating|Processing|Crunching|Reticulating|Whirring|Hashing|Synthesizing|Generating|Orchestrating|Architecting|Bootstrapping|Actualizing|Actioning|Accomplishing|Effecting|Working|Doing|Forming|Creating|Ionizing|Nucleating|Crystallizing|Coalescing|Combobulating|Recombobulating|Gitifying|Cascading)$/,
  hatch: /^(Hatching|Incubating|Nesting|Roosting)$/,
  spin: /^(Spinning|Swirling|Twisting|Whirlpooling|Discombobulating|Flummoxing|Befuddling|Topsy-turvying|Kerfuffling|Flibbertigibbeting|Wibbling|Fluttering|Undulating|Billowing|Flowing|Ebbing)$/,
  wander: /^(Wandering|Meandering|Moseying|Perambulating|Gallivanting|Lollygagging|Dilly-dallying|Puttering|Schlepping|Herding|Spelunking|Burrowing|Scampering|Scurrying|Skedaddling|Zigzagging|Galloping|Waddling|Slithering|Moonwalking|Pouncing)$/,
  garden: /^(Cultivating|Sprouting|Germinating|Photosynthesizing|Pollinating|Propagating|Symbioting|Osmosing)$/,
  space: /^(Hyperspacing|Orbiting|Levitating|Quantumizing|Warping|Swooping|Catapulting)$/,
  weather: /^(Thundering|Gusting|Precipitating|Misting|Nebulizing)$/,
  doodle: /^(Sketching|Doodling|Embellishing|Composing)$/,
  forge: /^(Forging|Crafting|Tinkering|Fiddle-faddling|Finagling|Wrangling|Mustering|Boondoggling|Shenaniganing|Tomfoolering|Hullaballooing|Whatchamacalliting)$/,
};

export const THINK_STYLES = ['bubble', ...Object.keys(STYLES)];

export function styleFor(verb) {
  for (const [style, re] of Object.entries(STYLES)) if (re.test(verb)) return style;
  return 'bubble';
}

export function randomVerb(style) {
  const pool = style ? VERBS.filter((v) => styleFor(v) === style) : VERBS;
  return pool[Math.floor(Math.random() * pool.length)] ?? 'Thinking';
}
