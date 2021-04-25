# Automated Notion-based Github Page

Notion's visuals make it great for a simple portfolio website but their public page isn't designed for website hosting.

Loconotion is a great python script that will parse a public Notion page and creae a static site.

This repo takes that a step further using Github Pages and Actions to build the static site into /docs. Updating the website is only done by triggering the workflow, meaning no files have to be manually handled or pushed.

## Usage

* Clone this repo and rename it
* Edit site.toml to use your Notion.so public link
* Make any other loconotion config changes in site.toml
* Run the CI workflow

## To-Do

See if Notion can somehow trigger a remote trigger for the workflow.
