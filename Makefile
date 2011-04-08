all: rebuild

clean:
	rm -f dump bulkloader-* *.pyc *.rej *.orig

upload:
	appcfg.py -e "$(MAIL)" update .

serve: .tmp/blobstore
	dev_appserver.py --enable_sendmail --use_sqlite --blobstore_path=.tmp/blobstore --datastore_path=.tmp/datastore -a 0.0.0.0 .

.tmp/blobstore:
	mkdir -p .tmp/blobstore
