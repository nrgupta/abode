const Anthropic = require("@anthropic-ai/sdk");
const config = require("../config");
const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

function deduplicateListings(listings) {
  const seen = new Set();
  return listings.filter(l => {
    const key = (l.url || l.title || "").toLowerCase().trim();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

async function analyzeListing(listing) {
  const prompt = `You are a smart apartment-hunting assistant helping someone find a great apartment in Chicago.

Analyze this listing and respond ONLY with a JSON object (no markdown, no extra text):

Listing:
- Title: ${listing.title}
- Price: ${listing.price}
- Location: ${listing.location}
- Source: ${listing.source}
- URL: ${listing.url}
- Beds: ${listing.beds || "unknown"}
- Baths: ${listing.baths || "unknown"}
- Sqft: ${listing.sqft || "unknown"}

Filters:
- Max Rent: $${config.search.maxRent}/mo
- Bedrooms: ${config.search.bedrooms}
- Preferred neighborhoods: ${config.preferredNeighborhoods.join(", ")}
- Bonus keywords: ${config.bonusKeywords.join(", ")}
- Red flag keywords: ${config.redFlagKeywords.join(", ")}

Return ONLY this JSON:
{
  "score": <number 1-10>,
  "summary": "<2-3 sentence summary>",
  "bonusFlags": ["<bonus keywords found>"],
  "redFlags": ["<red flag keywords found>"],
  "neighborhoodMatch": <true/false>,
  "withinBudget": <true/false>
}`;

  try {
    const response = await client.messages.create({
      model: "claude-sonnet-4-20250514",
      max_tokens: 500,
      messages: [{ role: "user", content: prompt }],
    });
    const text = response.content[0].text.trim();
    return { ...listing, ...JSON.parse(text.replace(/```json|```/g, "").trim()) };
  } catch (err) {
    console.error(`Agent error for "${listing.title}":`, err.message);
    return { ...listing, score: 5, summary: "Could not analyze.", bonusFlags: [], redFlags: [], neighborhoodMatch: false, withinBudget: true };
  }
}

async function runAgent(rawListings) {
  console.log(`\n🤖 Agent received ${rawListings.length} raw listings`);
  const unique = deduplicateListings(rawListings);
  console.log(`✅ After deduplication: ${unique.length} listings`);
  const analyzed = [];
  for (const listing of unique) {
    process.stdout.write(`   Analyzing: ${listing.title.slice(0, 50)}...`);
    const result = await analyzeListing(listing);
    analyzed.push(result);
    console.log(` score: ${result.score}/10`);
    await new Promise(r => setTimeout(r, 500));
  }
  analyzed.sort((a, b) => b.score - a.score);
  return analyzed;
}

module.exports = { runAgent };
