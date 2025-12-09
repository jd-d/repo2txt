# GitHub Repo to Text Converter (Local Directory Supported)

https://repo2txt.simplebasedomain.com/

This web-based tool converts GitHub repository (or local directory) contents  into a formatted text file for Large Language Model (LLM) prompts. It streamlines the process of transforming repository data into LLM-friendly input.

![demo.gif](demo.gif)



## Features

- Display GitHub repository structure
- Select files/directories to include
- Filter files by extensions
- Generate formatted text file
- Copy text to clipboard
- Download generated text
- Support for private repositories
- Browser-based for privacy and security
- Download zip of selected files
- Local directory support

This tool runs entirely in the browser, ensuring data security without server-side processing.

## Pythonista (iOS) version

A native Pythonista script is available at [`repo2txt_pythonista_ios.py`](repo2txt_pythonista_ios.py) with nearly the same UI and workflow as the web app:

1. Copy this repository into Pythonista on your iOS device.
2. Open `repo2txt_pythonista_ios.py` and run it.
3. Enter a GitHub URL (and optional token) and tap **Fetch Directory** to load the repo tree.
4. Toggle files or extensions, then tap **Generate Text** to build the combined prompt.
5. Use **Download Zip** to export selected files or **Copy/Save** to move the generated text into other apps.

Notes:
- For local content on iOS, use **Import Local (zip/file/folder)** to load a zipped project, an individual file, or an entire folder from the Files app.
- The script relies only on Pythonista-bundled modules plus `requests` (included with Pythonista).


## To do

- Compile tailwind css (gh action maybe?)
- python bindings

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the [MIT License](LICENSE).
