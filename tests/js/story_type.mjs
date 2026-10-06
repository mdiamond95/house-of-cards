// Types beat inputs with web/story/beats.js, for tests/test_story.py.
//
//     node tests/js/story_type.mjs inputs.json      -> [[beat, ...], ...] on stdout
//
// inputs.json is [input, ...] as hoc/export/beats.py turn_inputs builds them.
import { readFileSync } from 'node:fs';
import { typeTurn } from '../../web/story/beats.js';

const inputs = JSON.parse(readFileSync(process.argv[2], 'utf8'));
process.stdout.write(JSON.stringify(inputs.map(typeTurn)));
