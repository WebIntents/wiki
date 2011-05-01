all: rebuild

clean:
	find -iregex '.*\.\(pyc\|rej\|orig\)' -delete

console:
	PYTHONPATH=$(GAE_DIR):$(GAE_DIR)/lib/django_0_96 python

test:
	PYTHONPATH=$(GAE_DIR):$(GAE_DIR)/lib/django_0_96 python gaewiki/tests.py

upload: .hg/gaepass
	cat .hg/gaepass | appcfg.py -e "$(MAIL)" --passin update .

serve: .tmp/blobstore
	dev_appserver.py --enable_sendmail --use_sqlite --blobstore_path=.tmp/blobstore --datastore_path=.tmp/datastore -a 0.0.0.0 .

.tmp/blobstore:
	mkdir -p .tmp/blobstore

.hg/gaepass:
	$(EDITOR) .hg/gaepass
