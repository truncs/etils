/**
 * @fileoverview Tree manager.
 */

/**
 * Load the inner html of a node.
 * @param {string} id_ HTML id of the node
 */
async function load_content(id_) {
  const root = document.getElementById(id_);

  // Guard to only load the content once
  if (!root.classList.contains("loaded")) {
    root.classList.add("loaded");

    // Compute the HTML content in Python
    const html_content = await call_python('get_html_content', [root.id]);

    // Insert at the end, without destroying the one-line content
    root.insertAdjacentHTML('beforeend', html_content);

    // Register listeners for all newly added childs
    registerChildsEvent(root);
  }
}

/**
 * Register listerner for all childs.
 * @param {!HTMLElement} elem Todo
 */
function registerChildsEvent(elem) {
  const childs = elem.querySelectorAll(".register-onclick");
  for (const child of childs) {
    child.classList.remove("register-onclick");
    child.addEventListener("click", async function() {
      // Do not process the click if text is selected
      const selection = document.getSelection();
      if (selection.type === 'Range') {
        return;
      }

      // TODO(epot): As optimization, it's not required to query the id
      // each time, but instead use closure.
      // TODO(epot): Is there a way to only call this once ?
      await load_content(this.parentElement.id);

      // Toogle the collapsible section
      this.parentElement.querySelector(".collapsible").classList.toggle("active");
      this.classList.toggle("caret-down");
    });
  }
}
