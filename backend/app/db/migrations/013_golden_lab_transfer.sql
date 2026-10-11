-- Golden copy of the central-lab feed: the simulated lab desk corrects and adds records, so `reset` must restore the feed itself.
-- Taken at migration time, before any simulation can alter the feed.
CREATE TABLE IF NOT EXISTS golden.lab_transfer AS SELECT * FROM lab_vendor.transfer;
