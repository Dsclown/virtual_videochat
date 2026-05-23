'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const dist = path.join(ROOT, 'dist');

function copyIntoRoot(name) {
  const src = path.join(dist, name);
  const dst = path.join(ROOT, name);
  if (!fs.existsSync(src)) {
    return;
  }
  if (fs.statSync(src).isDirectory()) {
    if (fs.existsSync(dst)) {
      fs.rmSync(dst, { recursive: true });
    }
    fs.cpSync(src, dst, { recursive: true });
    return;
  }
  fs.copyFileSync(src, dst);
}

const builtHtml = path.join(dist, 'render.src.html');
if (fs.existsSync(builtHtml)) {
  fs.copyFileSync(builtHtml, path.join(ROOT, 'render.html'));
} else {
  copyIntoRoot('render.html');
}
copyIntoRoot('assets');
copyIntoRoot('Framework');

console.log('Deployed dist -> render-engine/cubism-sdk-live2d/');
