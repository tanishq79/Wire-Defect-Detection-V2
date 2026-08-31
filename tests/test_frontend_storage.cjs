// Exercise the actual saved-image UI helper without starting the Pi camera/UI.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../frontend/script.js'), 'utf8');
const helper = source.match(/function showStoredImages\(data\) \{[\s\S]*?\n\}/)[0];

function run(data, live) {
    const elements = Object.fromEntries(
        ['evidenceLink', 'storedPreviewLink', 'previewImage', 'previewWrap', 'cameraPreview', 'cameraEmpty']
            .map(id => [id, { src: 'existing-live-stream', style: { filter: 'brightness(2)' } }])
    );
    const revoked = [];
    const context = {
        data, API_BASE: 'http://pi:8000/', cameraPreviewActive: live,
        selectedObjectUrl: 'blob:selected-upload',
        document: { getElementById: id => elements[id] },
        URL: { revokeObjectURL: url => revoked.push(url) },
    };
    vm.runInNewContext(`${helper}\nshowStoredImages(data);`, context);
    return { elements, revoked, context };
}

const data = { images: {
    '640x320': { url: '/images/640x320/frame.png' },
    '1600x1200': { url: '/images/1600x1200/frame.png' },
} };
for (const live of [true, false]) {
    const { elements, revoked, context } = run(data, live);
    assert.equal(elements.previewImage.src, 'http://pi:8000/images/640x320/frame.png');
    assert.equal(elements.evidenceLink.href, 'http://pi:8000/images/1600x1200/frame.png');
    assert.equal(elements.evidenceLink.hidden, false);
    assert.equal(elements.storedPreviewLink.href, elements.previewImage.src);
    assert.equal(elements.storedPreviewLink.hidden, false);
    assert.equal(elements.previewWrap.style.display, 'block');
    assert.deepEqual(revoked, ['blob:selected-upload']);
    assert.equal(context.selectedObjectUrl, null);
    if (live) {
        assert.equal(elements.cameraPreview.src, 'existing-live-stream');
    } else {
        assert.equal(elements.cameraPreview.src, elements.previewImage.src);
        assert.equal(elements.cameraPreview.style.filter, '');
    }
}
const legacy = run({ prediction: 'ok_wire' }, false);
assert.equal(legacy.elements.evidenceLink.hidden, true);
assert.equal(legacy.elements.storedPreviewLink.hidden, true);
assert.equal(legacy.elements.cameraPreview.src, 'existing-live-stream');
assert.deepEqual(legacy.revoked, []);
console.log('3 frontend storage scenarios passed (saved image, live stream, legacy API).');
