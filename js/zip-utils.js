const CONFIG_FILENAME = '.repo2txtignore';

// Function to extract files from a zip archive
async function extractZipContents(zipFile) {
    try {
        const zip = await JSZip.loadAsync(zipFile);
        const tree = [];
        const gitignoreContent = ['.git/**'];
        let pathZipMap = {};
        let repo2txtConfig = { text: null, path: null };

        // Process each file in the zip
        for (const [relativePath, zipEntry] of Object.entries(zip.files)) {
            if (!zipEntry.dir) {
                tree.push({
                    path: relativePath,
                    type: 'blob',
                    urlType: 'zip', 
                    url: '',
                    lastModified: zipEntry.date instanceof Date ? zipEntry.date.getTime() : null
                });
                pathZipMap[relativePath] = zipEntry;

                if (relativePath.endsWith('.gitignore')) {
                    const content = await zipEntry.async('text');
                    gitignoreContent.push(...parseIgnoreFile(content, getParentPath(relativePath)));
                } else if (relativePath.endsWith(CONFIG_FILENAME)) {
                    const content = await zipEntry.async('text');
                    gitignoreContent.push(...parseIgnoreFile(content, getParentPath(relativePath)));
                    repo2txtConfig = { text: content, path: relativePath };
                }
            }
        }

        return { tree, gitignoreContent, pathZipMap, repo2txtConfig };
    } catch (error) {
        throw new Error(`Failed to extract zip contents: ${error.message}`);
    }
}

function parseIgnoreFile(content, basePath = '') {
    const prefix = basePath ? `${basePath}/` : '';
    return content
        .split(/\r?\n/)
        .map(line => line.trim())
        .filter(line => line && !line.startsWith('#'))
        .map(line => prefix ? `${prefix}${line}` : line);
}

function getParentPath(filePath) {
    const parts = filePath.split('/');
    parts.pop();
    return parts.join('/');
}

export { extractZipContents };
