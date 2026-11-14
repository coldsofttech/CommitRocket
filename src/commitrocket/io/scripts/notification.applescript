-- Shows a macOS notification. Title and body arrive in CR_TITLE and CR_BODY, never in the script text.
display notification (system attribute "CR_BODY") with title (system attribute "CR_TITLE")
