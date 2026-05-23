'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const CUBISM_ROOT = path.resolve(ROOT, '../../../CubismWebSamples');
const publicResources = [
  {
    src: path.join(CUBISM_ROOT, 'Framework/Shaders'),
    dst: path.join(ROOT, 'public/Framework/Shaders'),
  },
];

for (const entry of publicResources) {
  if (fs.existsSync(entry.dst)) {
    fs.rmSync(entry.dst, { recursive: true });
  }
  if (!fs.existsSync(entry.src)) {
    throw new Error(`Missing Cubism resource: ${entry.src}`);
  }
  fs.cpSync(entry.src, entry.dst, { recursive: true });
}

console.log('Cubism shaders copied to public/');
