// Reset the demo app's recipes: node seed.mjs empty|many
const seed = process.argv[2] ?? 'empty';
const port = Number(process.env.PORT ?? 4173);
const res = await fetch(`http://localhost:${port}/__seed/${seed}`, { method: 'POST' });
if (!res.ok) {
  console.error(`seed "${seed}" failed: ${res.status}`);
  process.exit(1);
}
console.log(`seeded "${seed}": ${(await res.json()).recipes} recipes`);
